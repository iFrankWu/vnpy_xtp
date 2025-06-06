import logging
import traceback
from time import sleep
from typing import Any, Dict, List
from datetime import datetime, time
from copy import copy
from vnpy.trader.database import stock_meta_repository
from vnpy.trader.database import sys_config_repository
from vnpy.event import EventEngine
from vnpy.trader.event import EVENT_TIMER
from vnpy.trader.constant import (
    Exchange,
    Product,
    Direction,
    OrderType,
    Status,
    Offset,
    OptionType
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    CancelRequest,
    OrderRequest,
    SubscribeRequest,
    TickData,
    ContractData,
    OrderData,
    TradeData,
    PositionData,
    AccountData
)
from vnpy.trader.utility import get_folder_path, round_to, ZoneInfo, DateUtil

from ..api import MdApi, TdApi, XTP_EXCHANGE_UNKNOWN

# 交易所映射
MARKET_XTP2VT: Dict[int, Exchange] = {
    1: Exchange.SZSE,
    2: Exchange.SSE
}
MARKET_VT2XTP: Dict[Exchange, int] = {v: k for k, v in MARKET_XTP2VT.items()}

EXCHANGE_XTP2VT: Dict[int, Exchange] = {
    1: Exchange.SSE,
    2: Exchange.SZSE,
}
EXCHANGE_VT2XTP: Dict[Exchange, int] = {v: k for k, v in EXCHANGE_XTP2VT.items()}

# 多空和开平方向映射
DIRECTION_STOCK_XTP2VT: Dict[int, Any] = {
    1: (Direction.LONG, Offset.NONE),
    2: (Direction.SHORT, Offset.NONE),
    21: (Direction.LONG, Offset.OPEN),
    22: (Direction.SHORT, Offset.OPEN),
    24: (Direction.LONG, Offset.CLOSE),
    23: (Direction.SHORT, Offset.CLOSE)
}
DIRECTION_STOCK_VT2XTP: Dict[Any, int] = {v: k for k, v in DIRECTION_STOCK_XTP2VT.items()}

DIRECTION_OPTION_XTP2VT: Dict[int, Direction] = {
    1: Direction.LONG,
    2: Direction.SHORT
}
DIRECTION_OPTION_VT2XTP: Dict[Direction, int] = {v: k for k, v in DIRECTION_OPTION_XTP2VT.items()}

# 持仓方向映射
POSITION_DIRECTION_XTP2VT = {
    0: Direction.NET,
    1: Direction.LONG,
    2: Direction.SHORT,
    3: Direction.SHORT
}

# 期权委托类型映射
OPTION_ORDERTYPE_XTP2VT: Dict[int, OrderType] = {
    1: OrderType.LIMIT,
    2: OrderType.MARKET,
    8: OrderType.FOK
}
OPTION_ORDERTYPE_VT2XTP: Dict[OrderType, int] = {v: k for k, v in OPTION_ORDERTYPE_XTP2VT.items()}

# 股票委托类型映射
EQUITY_ORDERTYPE_XTP2VT: Dict[int, OrderType] = {
    1: OrderType.LIMIT,
    4: OrderType.MARKET
}
EQUITY_ORDERTYPE_VT2XTP: Dict[OrderType, int] = {v: k for k, v in EQUITY_ORDERTYPE_XTP2VT.items()}

# 科创板委托类型映射
STAR_ORDERTYPE_XTP2VT: Dict[int, OrderType] = {
    1: OrderType.LIMIT,
    7: OrderType.MARKET
}
STAR_ORDERTYPE_VT2XTP: Dict[OrderType, int] = {v: k for k, v in STAR_ORDERTYPE_XTP2VT.items()}

# 通讯协议映射
PROTOCOL_VT2XTP: Dict[str, int] = {
    "TCP": 1,
    "UDP": 2
}

# 委托状态映射
STATUS_XTP2VT: Dict[int, Status] = {
    0: Status.SUBMITTING,
    1: Status.ALLTRADED,
    2: Status.PARTTRADED,
    3: Status.CANCELLED,
    4: Status.NOTTRADED,
    5: Status.CANCELLED,
    6: Status.REJECTED,
    7: Status.SUBMITTING
}

# 产品类型映射
PRODUCT_XTP2VT: Dict[int, Product] = {
    0: Product.EQUITY,
    1: Product.INDEX,
    2: Product.FUND,
    3: Product.BOND,
    4: Product.OPTION,
    5: Product.EQUITY,
    6: Product.FUND
}

# 开平方向映射
OFFSET_VT2XTP: Dict[Offset, int] = {
    Offset.NONE: 0,
    Offset.OPEN: 1,
    Offset.CLOSE: 2,
    Offset.CLOSETODAY: 4,
    Offset.CLOSEYESTERDAY: 5
}
OFFSET_XTP2VT: Dict[int, Offset] = {v: k for k, v in OFFSET_VT2XTP.items()}

# 业务类型映射
BUSINESS_VT2XTP: Dict[Any, int] = {
    "CASH": 0,
    Offset.NONE: 0,
    "MARGIN": 4,
    Offset.OPEN: 4,
    Offset.CLOSE: 4,
    "OPTION": 10,
}

# 期权类型映射
OPTIONTYPE_XTP2VT = {
    1: OptionType.CALL,
    2: OptionType.PUT
}

# 日志级别映射
LOGLEVEL_VT2XTP = {
    "FATAL": 0,
    "ERROR": 1,
    "WARNING": 2,
    "INFO": 3,
    "DEBUG": 4,
    "TRACE": 5,
}

# 其他常量
CHINA_TZ = ZoneInfo("Asia/Shanghai")  # 中国时区

# 合约数据全局缓存字典
symbol_contract_map: Dict[str, ContractData] = {}
# Chinese futures market trading period (day/night)
AM_START = time(9, 30)
AM_END = time(11, 30)

PM_START = time(13, 0)
PM_END = time(15, 0)


def is_curr_trade_time() -> datetime:
    current_time = datetime.now().time()
    trading = False
    if ((AM_START <= current_time <= AM_END)
            or (PM_START <= current_time <= PM_END)):
        trading = True
    return trading


class XtpGateway(BaseGateway):
    """
    VeighNa用于对接中泰XTP柜台的交易接口。

    由于xtp升级系统 提高tcp tick的推送能力 会造成socket连接断开，从而导致tick接收失败。
    因此在2023-12-02 进行以下升级：
        1、当前进程仅处理自身订阅标的的tick，其他tick直接丢弃，不进入队列
        2、丢弃早期的tick，以减少tick队列的积压
        3、断开重连sleep 3秒后 再重连
        4、重连时 先取消之前订阅的标的 （这是因为经过实践重连时 xtp可能订阅全市场标的 此时双方系统都会处理不过来）
        5、增加应急开关 re_auto_login_xtp，当设置为N时 则不会自动重连，默认自动重连
        6、tcp连接超时时间设置为30s
        7、增加记录重连次数
        8、UDP模式下 重连不会重新订阅
    """

    default_name: str = "XTP"

    default_setting: Dict[str, Any] = {
        "账号": "",
        "密码": "",
        "客户号": 1,
        "行情地址": "",
        "行情端口": 0,
        "交易地址": "",
        "交易端口": 0,
        "行情协议": ["TCP", "UDP"],
        "日志级别": ["FATAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"],
        "授权码": ""
    }

    exchanges: List[Exchange] = list(EXCHANGE_VT2XTP.keys())

    def __init__(self, event_engine: EventEngine, gateway_name: str):
        """构造函数"""
        super().__init__(event_engine, gateway_name)

        self.md_api: "XtpMdApi" = XtpMdApi(self)
        self.td_api: "XtpTdApi" = XtpTdApi(self)

    def connect(self, setting: dict) -> None:
        """连接交易接口"""
        userid: str = setting["账号"]
        password: str = setting["密码"]
        client_id: int = int(setting["客户号"])
        quote_ip: str = setting.get("行情地址")

        trader_ip: str = setting.get("交易地址")

        quote_protocol: str = setting["行情协议"]
        log_level: int = LOGLEVEL_VT2XTP[setting["日志级别"]]
        software_key: str = setting["授权码"]
        local_ip: str = setting["local_ip"]
        if quote_ip is not None:
            quote_port: int = int(setting.get("行情端口"))
            self.md_api.connect(
                userid, password, client_id, quote_ip,
                quote_port, quote_protocol, log_level,local_ip
            )
        if trader_ip is not None:
            trader_port: int = int(setting.get("交易端口"))
            self.td_api.connect(
                userid, password, client_id, trader_ip,
                trader_port, software_key, log_level,local_ip
            )
            self.init_query()

    def close(self) -> None:
        """关闭接口"""
        pass

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅行情"""
        self.md_api.subscribe(req)

    def subscribe_all_tickets(self) -> None:
        """订阅行情"""
        self.md_api.subscribe_all_tickets()

    def send_order(self, req: OrderRequest) -> str:
        """委托下单"""
        return self.td_api.send_order(req)

    def cancel_order(self, req: CancelRequest) -> None:
        """委托撤单"""
        self.td_api.cancel_order(req)

    def query_account(self) -> None:
        """查询资金"""
        self.td_api.query_account()

    def query_credit_asset(self) -> None:
        """查询信用资产"""
        self.td_api.query_credit_asset()

    def query_credit_debt(self) -> None:
        """查询信用负债"""
        self.td_api.query_credit_debt()



    def query_position(self) -> None:
        """查询持仓"""
        self.td_api.query_position()

    def process_timer_event(self, event) -> None:
        """定时事件处理"""
        if is_curr_trade_time():
            # 如果在交易期间就别执行了 影响性能
            return
        self.count += 1
        if self.count < 2:
            return
        self.count = 0

        func = self.query_functions.pop(0)
        func()
        self.query_functions.append(func)

    def init_query(self) -> None:
        """初始化查询任务"""
        self.count: int = 0
        self.query_account()
        self.query_credit_asset()

        # self.query_functions: list = [self.query_account, self.query_position]
        self.query_functions: list = [ self.query_position]
        self.event_engine.register(EVENT_TIMER, self.process_timer_event)

    def write_error(self, msg: str, error: dict) -> None:
        """输出错误信息"""
        error_id: int = error["error_id"]
        error_msg: str = error["error_msg"]
        msg: str = f"{msg}，代码：{error_id}，信息：{error_msg}"
        self.write_log(msg)

    def query_last_price(self,symbol,exchange:Exchange):
        cnt = 1
        self.md_api.query_last_price(symbol,exchange,cnt)

    def query_local_latest_tick_time(self, vt_symbol):
        return self.md_api.query_local_latest_tick_time(vt_symbol)


class XtpMdApi(MdApi):

    def __init__(self, gateway: XtpGateway):
        """构造函数"""
        super().__init__()

        self.gateway: XtpGateway = gateway
        self.gateway_name: str = gateway.gateway_name

        self.userid: str = ""
        self.password: str = ""
        self.client_id: int = 0
        self.server_ip: str = ""
        self.server_port: int = 0
        self.protocol: int = 0
        self.session_id: int = 0

        self.connect_status: bool = False
        self.login_status: bool = False

        self.sse_inited: bool = False
        self.szse_inited: bool = False
        # 记录当前进程点订阅了哪些标的 以便在连接断开重连的时候 重新订阅
        self.subscribe_request_list = set()
        # vt_symbol -> last tick time 将已过期的tick 早早的丢弃 免得队列积压
        self.last_tick_time : dict = {}

        self.re_connect_times = 0
        # 是否订阅全市场的tick 默认是false
        self.subscribe_all = False

        self.local_ip = "127.0.0.1"


    def onDisconnected(self, reason: int) -> None:
        """服务器连接断开回报"""
        self.connect_status = False
        self.login_status = False
        self.gateway.write_log(f"行情服务器连接断开, 原因{reason} clientId:{self.client_id} 已重连次数:{self.re_connect_times}")
        if len(self.subscribe_request_list) > 0:
            sys_config = sys_config_repository.get_config_value("re_auto_login_xtp")
            if sys_config is not None:
                if "Y".lower() != sys_config.config_value.lower():
                    logging.getLogger().info(
                        f'当前系统设置re_auto_login_xtp不为Y，为{sys_config.config_value}, 不自动重新订阅 clientId：{self.client_id} size：{len(self.subscribe_request_list)} {self.subscribe_request_list}')
                    return

        sleep(3)
        self.re_connect_times = self.re_connect_times + 1
        self.login_server()

    def onError(self, error: dict) -> None:
        """请求报错回报"""
        self.gateway.write_error("行情接口报错", error)
        logging.getLogger("error").error(f'行情接口报错:error{error},client_id:{self.client_id}')


    def onSubMarketData(self, data: dict, error: dict, last: bool) -> None:
        """订阅行情回报"""
        if not error or not error["error_id"]:
            return
        self.gateway.write_error("行情订阅失败", error)
        logging.getLogger("error").error(f'行情订阅失败 data:{data},error{error},client_id:{self.client_id}')


    def __is_sub_symbol(self,symbol):
        for sub_req in self.subscribe_request_list:
            sub_symbol = sub_req[0]
            if sub_symbol == symbol:
                return True
        return False

    def onDepthMarketData(self, data: dict) -> None:
        """行情推送回报"""
        timestamp: str = str(data["data_time"])
        dt: datetime = datetime.strptime(timestamp, "%Y%m%d%H%M%S%f")
        dt: datetime = dt.replace(tzinfo=CHINA_TZ)

        symbol = data["ticker"]
        exchange = EXCHANGE_XTP2VT[data["exchange_id"]]
        vt_symbol = f"{symbol}.{exchange.value}"

        last_tick_time = self.last_tick_time.get(vt_symbol)
        if last_tick_time is not None:
            if DateUtil.datetime_a_le_b(dt,last_tick_time):
                logging.getLogger().info(f'ignore received early tick:{vt_symbol},{dt}, already processed tick : {last_tick_time}')
                return

        if not self.subscribe_all and not self.__is_sub_symbol(data["ticker"]):
           logging.getLogger("error").error(
               f'received tick not our subscribed:{vt_symbol},{dt},clientId:{self.client_id} {data["last_price"]},subscribed:{self.subscribe_request_list}')
           return

        logging.getLogger().info(
           f'received tick:{vt_symbol},{dt},{data["open_price"]},{data["high_price"]},{data["low_price"]},{data["last_price"]}')


        tick: TickData = TickData(
            symbol=data["ticker"],
            exchange=EXCHANGE_XTP2VT[data["exchange_id"]],
            datetime=dt,
            volume=data["qty"],
            turnover=data["turnover"],
            last_price=data["last_price"],
            limit_up=data["upper_limit_price"],
            limit_down=data["lower_limit_price"],
            open_price=data["open_price"],
            high_price=data["high_price"],
            low_price=data["low_price"],
            pre_close=data["pre_close_price"],
            gateway_name=self.gateway_name
        )

        tick.bid_price_1, tick.bid_price_2, tick.bid_price_3, tick.bid_price_4, tick.bid_price_5 = data["bid"][0:5]
        tick.ask_price_1, tick.ask_price_2, tick.ask_price_3, tick.ask_price_4, tick.ask_price_5 = data["ask"][0:5]
        tick.bid_volume_1, tick.bid_volume_2, tick.bid_volume_3, tick.bid_volume_4, tick.bid_volume_5 = data["bid_qty"][
                                                                                                        0:5]
        tick.ask_volume_1, tick.ask_volume_2, tick.ask_volume_3, tick.ask_volume_4, tick.ask_volume_5 = data["ask_qty"][
                                                                                                        0:5]

        # 基于合约的最小价格跳动，对浮点数价格进行四舍五入
        contract: ContractData = symbol_contract_map.get(tick.vt_symbol, None)
        if contract:
            pricetick: float = contract.pricetick
            tick.last_price = round_to(data["last_price"], pricetick)
            tick.limit_up = round_to(data["upper_limit_price"], pricetick)
            tick.limit_down = round_to(data["lower_limit_price"], pricetick)
            tick.open_price = round_to(data["open_price"], pricetick)
            tick.high_price = round_to(data["high_price"], pricetick)
            tick.low_price = round_to(data["low_price"], pricetick)
            tick.pre_close = round_to(data["pre_close_price"], pricetick)

            tick.bid_price_1 = round_to(tick.bid_price_1, pricetick)
            tick.bid_price_2 = round_to(tick.bid_price_2, pricetick)
            tick.bid_price_3 = round_to(tick.bid_price_3, pricetick)
            tick.bid_price_4 = round_to(tick.bid_price_4, pricetick)
            tick.bid_price_5 = round_to(tick.bid_price_5, pricetick)
            tick.ask_price_1 = round_to(tick.ask_price_1, pricetick)
            tick.ask_price_2 = round_to(tick.ask_price_2, pricetick)
            tick.ask_price_3 = round_to(tick.ask_price_3, pricetick)
            tick.ask_price_4 = round_to(tick.ask_price_4, pricetick)
            tick.ask_price_5 = round_to(tick.ask_price_5, pricetick)

            tick.name = contract.name

        self.gateway.on_tick(tick)

        self.last_tick_time[vt_symbol] = dt

    def onQueryAllTickers(self, data: dict, error: dict, last: bool) -> None:
        """查询合约回报"""
        contract: ContractData = ContractData(
            symbol=data["ticker"],
            exchange=EXCHANGE_XTP2VT[data["exchange_id"]],
            name=data["ticker_name"],
            product=PRODUCT_XTP2VT[data["ticker_type"]],
            size=1,
            pricetick=data["price_tick"],
            min_volume=data["buy_qty_unit"],
            gateway_name=self.gateway_name
        )

        if contract.product != Product.OPTION:
            self.gateway.on_contract(contract)

        symbol_contract_map[contract.vt_symbol] = contract

        if last:
            self.gateway.write_log(f"{contract.exchange.value}合约信息查询成功")

            if contract.exchange == Exchange.SSE:
                self.sse_inited = True
            else:
                self.szse_inited = True

            # # 如果上海和深圳都查询完成后，再查询期权的信息
            # if self.sse_inited and self.szse_inited:
            #     self.gateway.td_api.query_option_info()

    def connect(
            self,
            userid: str,
            password: str,
            client_id: int,
            server_ip: str,
            server_port: int,
            quote_protocol: int,
            log_level: int,
            local_ip: str
    ) -> None:
        """连接服务器"""
        self.userid = userid
        self.password = password
        self.client_id = client_id
        self.server_ip = server_ip
        self.server_port = server_port
        self.protocol = PROTOCOL_VT2XTP[quote_protocol]
        self.local_ip = local_ip

        if not self.connect_status:
            path: str = str(get_folder_path(self.gateway_name.lower())).encode("GBK")
            self.createQuoteApi(self.client_id, path, log_level)
            #超时时间设置为30s
            self.setHeartBeatInterval(30)

            if quote_protocol == 'UDP':
                #如果连接的是UDP行情服务器，无论是否订阅，都是行情全接收后再本地Api筛选过滤
                 ##[15:05:04.868.840][3664962][INFO][XTP:0]Begin to init UDP session 230.1.53.91:7773, buffer frame size is -2147483648..
                # [15:05:04.868.868][3664962][INFO][XTP:0]group ip: 230.1.53.91, group port: 7773 local ip: 10.36.178.95 local port:7773 bind: 1
                # [15:05:04.868.922][3664962][INFO][XTP:0]UDP recv buf size: 425984
                # [15:05:04.868.928][3664962][INFO][XTP:0]UDP send buf size: 425984
                # [15:05:04.869.344][3664962][ERROR][XTP:10200104]Alloc UDP session error.[OS:12]Cannot allocate memory[xapi_udp_connect.cpp:47]
                self.setUDPBufferSize(1024)

                # 设定是否输出异步日志 灰度期间打开 生成时关闭
                # self.setUDPSeqLogOutPutFlag(True)

            self.login_server()
        else:
            self.gateway.write_log("行情接口已登录，请勿重复操作")

    def login_server(self) -> None:
        """用户登录"""
        n: int = self.login(
            self.server_ip,
            self.server_port,
            self.userid,
            self.password,
            self.protocol,
            self.local_ip
        )

        if not n:
            self.connect_status = True
            self.login_status = True
            msg: str = "行情服务器登录成功"
            self.query_contract()
            self.init()
            self.re_subscribe()
        else:
            error: dict = self.getApiLastError()
            msg: str = f"行情服务器登录失败，原因：{error['error_msg']}"

        self.gateway.write_log(msg)

    def close(self) -> None:
        """关闭连接"""
        if self.connect_status:
            self.exit()

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅行情"""
        if self.login_status:
            xtp_exchange: int = EXCHANGE_VT2XTP.get(req.exchange, "")
            self.subscribeMarketData(req.symbol, 1, xtp_exchange)
            logging.getLogger().info(f'首次订阅行情:{req.symbol},xtp_exchange:{xtp_exchange},client_id:{self.client_id}')
            ele = req.symbol, req.exchange
            # 仅在系统初始化的时候 添加值 其他时候不添加
            self.subscribe_request_list.add(ele)

    def subscribe_all_tickets(self) -> None:
        """订阅行情"""
        if self.login_status:
            #exchange_id：表示当前全订阅的市场，如果为XTP_EXCHANGE_UNKNOWN，表示沪深全市场（不包括新三板），XTP_EXCHANGE_SH表示为上海全市场，XTP_EXCHANGE_SZ表示为深圳全市场，XTP_EXCHANGE_NQ表示新三板
            self.subscribeAllMarketData(XTP_EXCHANGE_UNKNOWN)
            logging.getLogger().info(f'订阅全市场行情 xtp_exchange:{XTP_EXCHANGE_UNKNOWN},client_id:{self.client_id}')
            self.subscribe_all = True

    def query_last_price(self,symbol,exchange,cnt):
        xtp_exchange: int = EXCHANGE_VT2XTP.get(exchange, "")
        return self.queryTickersPriceInfo(symbol,cnt,xtp_exchange)


    def onQueryTickersPriceInfo(self, data: dict, error:dict, is_last:bool) -> None:
        # symbol = data["ticker"]
        # exchange = EXCHANGE_XTP2VT[data["exchange_id"]]
        # vt_symbol = f"{symbol}.{exchange.value}"
        logging.getLogger().info(f'response onQueryTickersPriceInfo :{data} {is_last}')

    def query_all_last_price(self,  exchange):
        xtp_exchange: int = EXCHANGE_VT2XTP.get(exchange, "")
        self.queryAllTickersFullInfo(xtp_exchange)

    def onQueryAllTickersPriceInfo(self, data: dict, error:dict, is_last:bool) -> None:
        logging.getLogger().info(f'response onQueryAllTickersPriceInfo:{data} {is_last}')


    # def onQueryAllTickersFullInfo(self, data: dict, error:dict, is_last:bool) -> None:
    #     logging.getLogger().info(f'response onQueryAllTickersFullInfo:{data}')

    def re_subscribe(self) -> None:
        """重新订阅行情"""
        try:
            if self.subscribe_request_list is None or len(self.subscribe_request_list) == 0:
                return
            if not self.login_status:
                logging.getLogger().info(
                    f'登录状态非法 不能重新订阅:clientId：{self.client_id} size：{len(self.subscribe_request_list)}')
                return
            #"TCP": 1, "UDP": 2
            # if self.protocol == 2:
            #     logging.getLogger().info(
            #         f'当前协议为UDP {self.protocol} (tcp:1,udp:2) 不需要重新订阅,clientId：{self.client_id} size：{len(self.subscribe_request_list)}')
            #     return

            sub_list_clone = self.subscribe_request_list
            # 1. 重新订阅之前 先取消订阅
            for req in sub_list_clone:
                symbol = req[0]
                exchange = req[1]

                xtp_exchange: int = EXCHANGE_VT2XTP.get(exchange, "")
                self.unSubscribeMarketData(symbol, 1, xtp_exchange)
                logging.getLogger().info(
                    f'重新订阅行情之前 先取消订阅:{symbol},xtp_exchange:{xtp_exchange}, client_id:{self.client_id}, size: {len(sub_list_clone)}')

            # 2. 重新订阅
            for req in sub_list_clone:
                symbol = req[0]
                exchange = req[1]
                xtp_exchange: int = EXCHANGE_VT2XTP.get(exchange, "")
                self.subscribeMarketData(symbol, 1, xtp_exchange)
                logging.getLogger().info(f'重新订阅行情:{symbol},xtp_exchange:{xtp_exchange}, client_id:{self.client_id}, size:{len(sub_list_clone)}')
        except:
            logging.getLogger("error").error(
                f"重新订阅行情出错 client_id:{self.client_id},session_id:{self.session_id} {traceback.format_exc()}")

    def query_contract(self) -> None:
        """查询合约信息"""
        for exchange_id in EXCHANGE_XTP2VT.keys():
            self.queryAllTickers(exchange_id)

    def query_local_latest_tick_time(self,vt_symbol):
        return self.last_tick_time.get(vt_symbol)


class XtpTdApi(TdApi):

    def __init__(self, gateway: XtpGateway):
        """"""
        super().__init__()

        self.gateway: XtpGateway = gateway
        self.gateway_name: str = gateway.gateway_name

        self.userid: str = ""
        self.password: str = ""
        self.client_id: str = ""
        self.server_ip: str = ""
        self.server_port: str = ""
        self.software_key: str = ""

        self.session_id: int = 0
        self.reqid: int = 0
        self.protocol: int = 0
        self.local_ip = "127.0.0.1"

        # 账户是否支持两融或者期权交易
        self.margin_trading = False
        self.option_trading = False

        self.connect_status: bool = False
        self.login_status: bool = False

        self.short_positions: Dict[str, PositionData] = {}
        self.orders: Dict[str, OrderData] = {}

    def onDisconnected(self, session: int, reason: int) -> None:
        """服务器连接断开回报"""
        self.connect_status = False
        self.login_status = False
        self.gateway.write_log(f"交易服务器连接断开, 原因{reason}")

        self.login_server()

    def onError(self, error: dict) -> None:
        """请求报错回报"""
        self.gateway.write_error("交易接口报错", error)

    def onOrderEvent(self, data: dict, error: dict, session: int) -> None:
        """委托状态更新"""
        if error["error_id"]:
            self.gateway.write_error("交易委托失败了！！", error)
            self.gateway.write_log(f"交易委托失败了2{data}")

        symbol: str = data["ticker"]
        if len(symbol) == 8:
            direction: Direction = DIRECTION_OPTION_XTP2VT[data["side"]]
            offset: Offset = OFFSET_XTP2VT[data["position_effect"]]
            order_type: OrderType = OPTION_ORDERTYPE_XTP2VT.get(data["price_type"], OrderType.MARKET)
        else:
            direction, offset = DIRECTION_STOCK_XTP2VT[data["side"]]

            if symbol.startswith("688"):
                type_map: dict = STAR_ORDERTYPE_XTP2VT
            else:
                type_map: dict = EQUITY_ORDERTYPE_XTP2VT
            order_type: OrderType = type_map.get(data["price_type"], OrderType.MARKET)

        orderid: str = str(data["order_xtp_id"])
        if orderid not in self.orders:
            order: OrderData = OrderData(
                symbol=symbol,
                exchange=MARKET_XTP2VT[data["market"]],
                orderid=orderid,
                type=order_type,
                direction=direction,
                offset=offset,
                price=data["price"],
                volume=data["quantity"],
                traded=data["qty_traded"],
                status=STATUS_XTP2VT[data["order_status"]],
                gateway_name=self.gateway_name
            )
            self.orders[orderid] = order
        else:
            order: OrderData = self.orders[orderid]
            order.traded = data["qty_traded"]
            order.status = STATUS_XTP2VT[data["order_status"]]

        if not order.datetime:
            timestamp: str = str(data["insert_time"])
            dt: datetime = datetime.strptime(timestamp, "%Y%m%d%H%M%S%f")
            dt: datetime = dt.replace(tzinfo=CHINA_TZ)
            order.datetime = dt
        self.gateway.on_order(copy(order))

    def onTradeEvent(self, data: dict, session: int) -> None:
        """成交推送"""
        # logging.getLogger().info(f"onTradeEvent:{data}")

        symbol: str = data["ticker"]
        if len(symbol) == 8:
            direction: Direction = DIRECTION_OPTION_XTP2VT[data["side"]]
            offset: Offset = OFFSET_XTP2VT[data["position_effect"]]
        else:
            direction, offset = DIRECTION_STOCK_XTP2VT[data["side"]]

        timestamp: str = str(data["trade_time"])
        dt: datetime = datetime.strptime(timestamp, "%Y%m%d%H%M%S%f")
        dt: datetime = dt.replace(tzinfo=CHINA_TZ)

        trade: TradeData = TradeData(
            symbol=symbol,
            exchange=MARKET_XTP2VT[data["market"]],
            orderid=str(data["order_xtp_id"]),
            tradeid=str(data["exec_id"]),
            direction=direction,
            offset=offset,
            price=data["price"],
            volume=data["quantity"],
            datetime=dt,
            gateway_name=self.gateway_name
        )

        if trade.orderid in self.orders:
            order: OrderData = self.orders[trade.orderid]
            order.traded += trade.volume

            if order.traded < order.volume:
                order.status = Status.PARTTRADED
            else:
                order.status = Status.ALLTRADED
            self.gateway.on_order(copy(order))
        else:
            self.gateway.write_log(f"成交找不到对应委托{trade.orderid}")

        self.gateway.on_trade(trade)
        if order.status in [Status.PARTTRADED,Status.ALLTRADED]:
            # 每次成交时 触发资产更新
            self.query_account()
            self.query_credit_asset()

    def onCancelOrderError(self, data: dict, error: dict, session: int) -> None:
        """撤单报错"""
        if not error or not error["error_id"]:
            return

        self.gateway.write_error("撤单失败", error)

    def onQueryPosition(
            self,
            data: dict,
            error: dict,
            request: int,
            last: bool,
            session: int
    ) -> None:
        """查询持仓回报"""
        if data["market"] == 0:
            return

        position: PositionData = PositionData(
            symbol=data["ticker"],
            exchange=MARKET_XTP2VT[data["market"]],
            direction=POSITION_DIRECTION_XTP2VT[data["position_direction"]],
            volume=data["total_qty"],
            frozen=data["total_qty"] - data["sellable_qty"],
            price=data["avg_price"],
            pnl=data["unrealized_pnl"],
            yd_volume=data["yesterday_position"],
            gateway_name=self.gateway_name
        )
        self.gateway.on_position(position)

    def onQueryAsset(
            self,
            data: dict,
            error: dict,
            request: int,
            last: bool,
            session: int
    ) -> None:
        """查询资金回报"""
        # logging.getLogger().info(f"onQueryAsset:{data}")

        account: AccountData = AccountData(
            accountid=self.userid,
            balance=round(data["total_asset"], 2),
            frozen=round(data["withholding_amount"], 2),
            total_asset= round(data["total_asset"], 2),
            buying_power = round(data["buying_power"], 2),
            withholding_amount = round(data["withholding_amount"], 2),
            fund_buy_amount = round(data["fund_buy_amount"], 2),
            all_asset = 0,
            all_debt = 0,
            guaranty = 0,
            maintenance_ratio = 0,
            line_of_credit = 0,
            gateway_name=self.gateway_name,
            asset_type='CASH'
        )
        account.available = round(data["buying_power"], 2)


        if data["account_type"] == 1:
            self.margin_trading = True
        elif data["account_type"] == 2:
            account.frozen = account.balance - account.available - data["security_asset"]
            account.frozen = round(account.frozen, 2)
            self.option_trading = True

        self.gateway.on_account(account)

    def onQueryCreditFundInfo(self, data: dict,
            error: dict,
            request: int,
            session: int):
        # logging.getLogger().info(f"onQueryCreditFundInfo:{data}")

        if error is not None and error.get("error_id") is not None and len(error.get('error_msg')) > 1 :
            logging.getLogger("error").error(f"获取信用资产出错 {error}  reqId:{request} session:{session}")
            return

        account: AccountData = AccountData(
            accountid=self.userid,
            balance=0,
            frozen=0,
            total_asset=0,
            buying_power=0,
            withholding_amount=0,
            fund_buy_amount=0,
            all_asset=round(data["all_asset"], 2),
            all_debt=round(data["all_debt"], 2),
            guaranty=round(data["guaranty"], 2),
            maintenance_ratio=round(data["maintenance_ratio"], 2),
            line_of_credit=round(data["line_of_credit"], 2),
            gateway_name=self.gateway_name,
            asset_type='CREDIT'
        )
        self.gateway.on_account(account)

    def onQueryOptionAuctionInfo(self, data: dict, error: dict, reqid: int, last: bool, session: int) -> None:
        """查询期权合约细节回报"""
        if not data or not data["ticker"]:
            return

        contract: ContractData = ContractData(
            symbol=data["ticker"],
            exchange=MARKET_XTP2VT[data["security_id_source"]],
            name=data["symbol"],
            product=Product.OPTION,
            size=data["contract_unit"],
            min_volume=data["qty_unit"],
            pricetick=data["price_tick"],
            gateway_name=self.gateway_name
        )

        contract.option_portfolio = data["underlying_security_id"] + "_O"
        contract.option_underlying = (
                data["underlying_security_id"]
                + "-"
                + str(data["delivery_month"])
        )
        contract.option_type = OPTIONTYPE_XTP2VT.get(data["call_or_put"], None)

        contract.option_strike = data["exercise_price"]
        contract.option_expiry = datetime.strptime(
            str(data["last_trade_date"]), "%Y%m%d"
        )
        contract.option_index = get_option_index(
            contract.option_strike, data["contract_id"]
        )

        self.gateway.on_contract(contract)
        symbol_contract_map[contract.vt_symbol] = contract

        if last:
            self.gateway.write_log("期权信息查询成功")

    def onQueryCreditDebtInfo(
            self,
            data: dict,
            error: dict,
            request: int,
            last: bool,
            session: int
    ) -> None:
        """查询两融持仓回报"""
        # logging.getLogger().info(f"OnQueryCreditDebtInfo:{data}")

        if data["debt_type"] == 1:
            symbol: str = data["ticker"]
            exchange: Exchange = MARKET_XTP2VT[data["market"]]

            position: PositionData = self.short_positions.get(symbol, None)
            if not position:
                position = PositionData(
                    symbol=symbol,
                    exchange=exchange,
                    direction=Direction.SHORT,
                    gateway_name=self.gateway_name
                )
                self.short_positions[symbol] = position

            position.volume += data["remain_qty"]

        if last:
            for position in self.short_positions.values():
                self.gateway.on_position(position)

            self.short_positions.clear()

    def connect(
            self,
            userid: str,
            password: str,
            client_id: int,
            server_ip: str,
            server_port: int,
            software_key: str,
            log_level: int,
            local_ip:str
    ) -> None:
        """连接服务器"""

        self.userid = userid
        self.password = password
        self.client_id = client_id
        self.server_ip = server_ip
        self.server_port = server_port
        self.software_key = software_key
        self.protocol = PROTOCOL_VT2XTP["TCP"]
        self.local_ip = local_ip

        if not self.connect_status:
            path: str = str(get_folder_path(self.gateway_name.lower())).encode("GBK")
            self.createTraderApi(self.client_id, path, log_level)

            self.setSoftwareKey(self.software_key)
            self.subscribePublicTopic(0)
            self.login_server()
        else:
            self.gateway.write_log("交易接口已登录，请勿重复操作")

    def login_server(self) -> None:
        """登录"""
        n: int = self.login(
            self.server_ip,
            self.server_port,
            self.userid,
            self.password,
            self.protocol
        )

        if n:
            self.session_id = n
            self.connect_status = True
            self.login_status = True
            msg: str = f"交易服务器登录成功, 会话编号：{self.session_id}"
            self.init()
            self.init_contract_data()
        else:
            error: dict = self.getApiLastError()
            msg: str = f"交易服务器登录失败，原因：{error['error_msg']}"

        self.gateway.write_log(msg)
        self.query_option_info()

    def close(self) -> None:
        """关闭连接"""
        if self.connect_status:
            self.exit()

    def query_option_info(self) -> None:
        """查询期权信息"""
        self.reqid += 1
        self.queryOptionAuctionInfo({}, self.session_id, self.reqid)

    def send_order(self, req: OrderRequest) -> str:
        """委托下单"""
        if req.exchange not in MARKET_VT2XTP:
            self.gateway.write_log(f"委托失败，不支持的交易所{req.exchange.value}")
            return ""

        if self.margin_trading and req.offset == Offset.NONE:
            self.gateway.write_log("委托失败，两融交易需要选择开平方向")
            return ""

        # 期权委托
        if len(req.symbol) == 8:
            if req.type not in OPTION_ORDERTYPE_VT2XTP:
                self.gateway.write_log(f"委托失败，不支持的期权委托类型{req.type.value}")
                return ""

            xtp_req: dict = {
                "ticker": req.symbol,
                "market": MARKET_VT2XTP[req.exchange],
                "price": req.price,
                "quantity": int(req.volume),
                "side": DIRECTION_OPTION_VT2XTP.get(req.direction, ""),
                "position_effect": OFFSET_VT2XTP[req.offset],
                "price_type": OPTION_ORDERTYPE_VT2XTP[req.type],
                "business_type": 10
            }
        # 股票委托
        else:
            # 科创版
            if req.symbol.startswith("688"):
                type_map: dict = STAR_ORDERTYPE_VT2XTP
            # 其他
            else:
                type_map: dict = EQUITY_ORDERTYPE_VT2XTP

            if req.type not in type_map:
                self.gateway.write_log(f"委托失败，不支持的股票委托类型{req.type.value}")
                return ""

            xtp_req: dict = {
                "ticker": req.symbol,
                "market": MARKET_VT2XTP[req.exchange],
                "price": req.price,
                "quantity": int(req.volume),
                "price_type": type_map[req.type],
            }
            if self.margin_trading :
                is_buy_with_rongzi = req.get_is_buy_with_rongzi()
                if is_buy_with_rongzi is not None and is_buy_with_rongzi:
                    xtp_req["side"] = DIRECTION_STOCK_VT2XTP.get((req.direction, req.offset), "")
                    xtp_req["business_type"] = 4
                else:
                    # 信用户进行普通交易时，要使用担保品买、担保品卖，business_type = 4，Side = 28/29
                    xtp_req["business_type"] = 4
                    xtp_req["side"] = DIRECTION_STOCK_VT2XTP.get((req.direction, Offset.NONE), "")

            else:
                xtp_req["side"] = DIRECTION_STOCK_VT2XTP.get((req.direction, Offset.NONE), "")
                xtp_req["business_type"] = 0

        orderid: int = self.insertOrder(xtp_req, self.session_id)
        orderid: str = str(orderid)

        order: OrderData = req.create_order_data(orderid, self.gateway_name)
        self.orders[orderid] = order
        self.gateway.on_order(copy(order))

        return order.vt_orderid

    def cancel_order(self, req: CancelRequest) -> None:
        """委托撤单"""
        self.cancelOrder(int(req.orderid), self.session_id)

    def query_account(self) -> None:
        """查询资金"""
        if not self.connect_status:
            return

        self.reqid += 1
        self.queryAsset(self.session_id, self.reqid)

    def query_position(self) -> None:
        """查询持仓"""
        if not self.connect_status:
            return

        self.reqid += 1
        self.queryPosition("", self.session_id, self.reqid)

        if self.margin_trading:
            self.reqid += 1
            self.queryCreditDebtInfo(self.session_id, self.reqid)

    def query_credit_asset(self):
        if not self.connect_status:
            return

        # if self.margin_trading:
        self.reqid += 1
        # logging.getLogger().info(f"queryCreditFundInfo reqId:{self.reqid} ,session:{self.session_id}")
        self.queryCreditFundInfo(self.session_id,self.reqid)

    def query_credit_debt(self):
        if not self.connect_status:
            return

        # if self.margin_trading:
        self.reqid += 1
        # logging.getLogger().info(f"query_credit_debt reqId:{self.reqid} ,session:{self.session_id}")
        self.queryCreditDebtInfo(self.session_id, self.reqid)

    def init_contract_data(self):
        contract_list = stock_meta_repository.get_all_contracts()
        for contrat in contract_list:
            symbol_contract_map[contrat.vt_symbol] = contrat


def get_option_index(strike_price: float, exchange_instrument_id: str) -> str:
    """获取期权索引"""
    exchange_instrument_id: str = exchange_instrument_id.replace(" ", "")

    if "M" in exchange_instrument_id:
        n: int = exchange_instrument_id.index("M")
    elif "A" in exchange_instrument_id:
        n: int = exchange_instrument_id.index("A")
    elif "B" in exchange_instrument_id:
        n: int = exchange_instrument_id.index("B")
    else:
        return str(strike_price)

    index: str = exchange_instrument_id[n:]
    option_index: str = f"{strike_price:.3f}-{index}"

    return option_index
