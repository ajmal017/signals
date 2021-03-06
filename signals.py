import pandas as pd
import datetime
from collections import defaultdict
from indicators import SuperTrend
from datetime import datetime
import json


ohlc_dict = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}


loaded = {}


def load_ticker(ticker, sample_mins=None):
    if (ticker, sample_mins) in loaded:
        return loaded[(ticker, sample_mins)]

    filename = f"./csv/{ticker}.csv"
    # print(f"Loading {filename}")
    try:
        df = pd.read_csv(
            filename,
            names=["Datetime", "Open", "High", "Low", "Close"],
            index_col="Datetime",
            parse_dates=True,
            infer_datetime_format=True,
        )
        # Fix forexit timezone
        # See last post here: https://forextester.com/forum/viewtopic.php?t=3175
        # If I adjust the signal time to be one hour forward, I get the correct time.
        # So I need to adjust the forex time to be one hour backwards
        df = df.set_index(df.index.values - pd.Timedelta(hours=1))
        df.sort_index(inplace=True)
        if sample_mins:
            df = df.resample(f"{sample_mins}Min").apply(ohlc_dict).dropna()

        loaded[(ticker, sample_mins)] = df
        return df
    except:
        return None


class Signal:
    def __init__(
        self, ticker, datetime_str, entry_price, stop_loss, take_profit, text=None
    ):
        # Signal time needs to be in the format '2020-02-01 19:34'
        self.datetime_str = datetime_str
        # self.signal_time = datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        self.entry_price = float(entry_price)
        self.real_entry_price = self.entry_price
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        self.type = "BUY" if entry_price > stop_loss else "SELL"
        self.ticker = ticker
        self.text = text

    def __str__(self):
        return f"{self.ticker}: {self.datetime_str}: Entry: {self.real_entry_price:.5f}, SL: {self.stop_loss:.5f}, TP: {self.take_profit:.5f}"

    def set_stop_loss_pips(self, new_stop_loss):
        stop_loss_pair_val = new_stop_loss / pip_factor(self.ticker)
        if self.type == "BUY":
            self.stop_loss = self.entry_price - stop_loss_pair_val
        if self.type == "SELL":
            self.stop_loss = self.entry_price + stop_loss_pair_val

    def set_take_profit_pips(self, new_take_profit):
        take_profit_pair_val = new_take_profit / pip_factor(self.ticker)
        if self.type == "BUY":
            self.take_profit = self.entry_price + take_profit_pair_val
        if self.type == "SELL":
            self.take_profit = self.entry_price - take_profit_pair_val


def pip_factor(ticker):
    factor = 10000
    if "JPY" in ticker:
        factor = 100

    if "XAU" in ticker:
        factor = 10
    return factor


def parse_beta_signal(date_time, text):
    """
    date_time is a str, like 2019-05-21T14:55:09
    text is str, like:
    PAR : GBPUSD 

    Acción : BUY

    Entrada : 1.27230

    SL : 1.26000
    TP : OPEN
    """
    # TODO: Add take profits here
    # Signal: ticker, datetime_str, entry_price, stop_loss, take_profit
    ticker = None
    entry_price = None
    stop_loss = None
    # take_profit = None

    lines = text.upper().splitlines()
    for line in lines:
        if not line:
            continue
        try:
            if line.startswith("PAR"):
                ticker = line.split(sep=":")[1].split()[0]
            if line.startswith("ENTRADA"):
                entry_price = float(line.split(sep=":")[1].split()[0])
            if line.startswith("SL"):
                if ":" in line:
                    stop_loss = float(line.split(sep=":")[1].split()[0])
                else:
                    stop_loss = float(line.split()[1])

        except Exception as ex:
            print(ex)
    if ticker and entry_price and stop_loss:
        return Signal(ticker, date_time, entry_price, stop_loss, 0.0, text)
    return None


cached_signals = None


def load_beta_trades(telegram_filename, slippage=10):
    global cached_signals
    if cached_signals:
        return cached_signals
    print("Loading Trades...")
    slip = 0
    bad_ticker = 0
    with open(telegram_filename) as d:
        dump = json.load(d)
    beta = dump["chats"]["list"][0]["messages"]
    signals = []
    for m in beta:
        if not isinstance(m["text"], str):
            continue
        if "ENTRADA" in m["text"].upper():
            signal = parse_beta_signal(m["date"], m["text"])
            if signal:
                df = load_ticker(signal.ticker)
                if df is not None:
                    # Load the actual entry price for this date from our data
                    # It looks like Beta sometimes gets it wrong
                    ohlc_values = df.loc[signal.datetime_str :].iterrows()
                    _, first_ohlc = next(ohlc_values)
                    signal.real_entry_price = first_ohlc.Open
                    if (
                        abs(signal.entry_price - signal.real_entry_price)
                        * pip_factor(signal.ticker)
                        < slippage
                    ):
                        signals.append(signal)
                    else:
                        # print(f"Slippage to high for: {signal}")
                        slip += 1
                else:
                    # print(f"Could not load ticker: {signal.ticker}")
                    bad_ticker += 1
    cached_signals = signals
    print(
        f"Loaded {len(signals)} signal, failed: Slippage = {slip}, Unknown ticker = {bad_ticker}"
    )
    return signals


def load_beta_trades_from_csv(filename):
    signals = defaultdict(list)
    with open(filename, "r") as f:
        next(f)  # Skip header row
        for signal in f:
            tokens = signal.split(",")
            datetime = tokens[0].strip()
            ticker = tokens[1].strip()
            signal_type = tokens[2].strip()
            entry = tokens[3].strip()
            tp1 = tokens[4].strip()
            tp2 = tokens[6].strip()
            tp3 = tokens[8].strip()
            sl = tokens[10].strip()
            signals["TP1"].append(Signal(ticker, datetime, entry, sl, tp1))
            signals["TP2"].append(Signal(ticker, datetime, entry, sl, tp2))
            signals["TP3"].append(Signal(ticker, datetime, entry, sl, tp3))
    return signals
