import curses
import contextlib
import typing as t
import logging
import textwrap
import time
import subprocess
import sys
import traceback
import socket
import threading
import platform
import base64
import datetime
import os
import json
import decimal
import string
from dataclasses import dataclass
from pathlib import Path
from collections import namedtuple
from curses.textpad import Textbox

logger = logging.getLogger("ui")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super(DecimalEncoder, self).default(o)


colr = curses.color_pair
_use_color_no_tty = True


def use_color():
    if sys.stdout.isatty():
        return True
    if _use_color_no_tty:
        return True
    return False


def open_file_browser():
    plat = platform.system()

    if plat == "Linux":
        cmd = "xdg-open ."
    elif plat == "Darwin":
        cmd = "open ."
    elif plat == "Windows":
        cmd = "explorer ."

    subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def esc(*codes: t.Union[int, str]) -> str:
    """Produces an ANSI escape code from a list of integers
    :rtype: text_type
    """
    return t_("\x1b[{}m").format(t_(";").join(t_(str(c)) for c in codes))


def t_(b: t.Union[bytes, t.Any]) -> str:
    """ensure text type"""
    if isinstance(b, bytes):
        return b.decode()
    return b


def conn_line(msg: str) -> str:
    return green(bold(" ○  ")) + msg


# 8 bit Color
###############################################################################
#
# TODO this color stuff was taken from some Github page; track it down and credit
# the authos.


def make_color(start, end: str) -> t.Callable[[str], str]:
    def color_func(s: str) -> str:
        if not use_color():
            return s

        # render
        return start + t_(s) + end

    return color_func


FG_END = esc(39)
red = make_color(esc(31), FG_END)
green = make_color(esc(32), FG_END)
yellow = make_color(esc(33), FG_END)
blue = make_color(esc(34), FG_END)
cyan = make_color(esc(36), FG_END)
bold = make_color(esc(1), esc(22))


class Action:
    pass


class Spinner:
    def __init__(self):
        self.i = -1

    def spin(self) -> str:
        self.i += 1
        return ["◰", "◳", "◲", "◱"][self.i % 4]


class OutputFormatter:
    def __init__(self):
        self.spinner = Spinner()

    def p(self, msg: str = "", clear=False, **kwargs):
        if clear:
            msg = f"\r{msg}"
        else:
            msg += "\n"
        print(msg, flush=True, file=sys.stderr, end="", **kwargs)

    def task(self, s: str, **kwargs):
        self.p(bold(" □  ") + s, **kwargs)

    def blank(self, s: str, **kwargs):
        self.p("    " + s, **kwargs)

    def done(self, s: str, **kwargs):
        self.p(green(bold(" ✔  ")) + s, **kwargs)

    def alert(self, s: str, **kwargs):
        self.p(f" {yellow('!')}  " + s, **kwargs)

    def info(self, s: str, **kwargs):
        self.p(" -- " + s, **kwargs)

    def inp(self, s: str) -> str:
        got = input(yellow(" ?  ") + s).strip()
        self.p()
        return got

    def warn(self, s: str, **kwargs):
        self.p(red(bold(" !  ")) + s, **kwargs)

    def spin(self, s: str):
        self.p(f" {self.spinner.spin()}  {s} ", clear=True)

    def section(self, s: str):
        self.p()
        self.p(f" {bold('#')}  {bold(s)}")
        self.p(f"    {'-' * len(s)}")
        self.p()

    def finish_setup(self, config=None, wallet=None) -> t.Tuple[int, Action]:
        self.p()
        time.sleep(1)
        self.blank("   enjoy your wallet, and remember...")
        time.sleep(1.5)
        print(textwrap.indent(neversell, "     "))
        self.p()
        input("    press [enter] to return home ")
        return (config, wallet)


F = OutputFormatter()


class Scene:
    def __init__(self, scr, conf, wconfs, controller):
        self.scr = scr
        self.config = conf
        self.wallet_configs = wconfs
        self.controller = controller

    def draw(self, k: int) -> t.Tuple[int, Action]:
        pass


class MenuItem(namedtuple("MenuItem", "idx,title,action")):
    def args(self, mchoice):
        return (self.idx, self.title, mchoice == self)


def run_setup(config, controller) -> t.Tuple[t.Any, t.Any]:
    curses.endwin()
    os.system("cls" if os.name == "nt" else "clear")

    formatter = OutputFormatter()
    p = formatter.p
    section = formatter.section
    inp = formatter.inp
    blank = formatter.blank
    warn = formatter.warn
    info = formatter.info
    done = formatter.done
    task = formatter.task
    spin = formatter.spin
    finish = formatter.finish_setup

    title = cyan(
        r"""
                          .
                        .o8
    .oooo.o  .ooooo.  .o888oo oooo  oooo  oo.ooooo.
   d88(  "8 d88' `88b   888   `888  `888   888' `88b
   `"Y88b.  888ooo888   888    888   888   888   888
   o.  )88b 888    .o   888 .  888   888   888   888
   8""888P' `Y8bod8P'   "888"  `V88V"V8P'  888bod8P'
                                           888
                                          o888o

"""
    )
    p(title)

    blank("searching for Bitcoin Core...")
    rpc = controller.discover_rpc(config)
    if not rpc:
        warn("couldn't detect Bitcoin Core - make sure it's running locally, or")
        warn("use `coldcore --rpc <url>`")
        sys.exit(1)

    hoststr = yellow(f"{rpc.host}:{rpc.port}")
    p(conn_line(f"connected to Bitcoin Core at {hoststr}"))
    p()

    def delay(t: float = 1.0):
        time.sleep(t)

    use_gpg = False
    if not config:
        section("coldcore config file setup")
        delay()
        pre = "you can encrypt your config file with"

        if controller.has_gpg():
            prompt = "do you want to use GPG to encrypt your coldcore config? [y/N] "
            if inp(prompt) == "y":
                use_gpg = True

        if controller.has_pass():
            info(f"{pre} pass by prefixing your path with 'pass:'")
            p()
            delay()

        defaultpath = controller.suggested_config_path(use_gpg)
        where = inp(f"where should I store your config? [{defaultpath}] ")
        where = where or defaultpath
        config = controller.create_config(where, rpc.url)
    else:
        if config.loaded_from.endswith(".gpg"):
            use_gpg = True
        done(f"loaded config from {yellow(config.loaded_from)}")

    if not config:
        warn("Couldn't obtain config. Exiting.")
        sys.exit(1)

    p()

    section("Coldcard hardware setup")

    inp(
        "have you set up your Coldcard "
        "(https://coldcardwallet.com/docs/quick)? [press enter] "
    )

    blank("checking Bitcoin Core sync progres...")
    chaininfo = {"verificationprogress": 0}
    while chaininfo["verificationprogress"] < 0.999:
        try:
            chaininfo = rpc.getblockchaininfo()
        except Exception:
            pass
        prog = "%.2f" % (chaininfo["verificationprogress"] * 100)
        info(f"initial block download progress: {prog}%", clear=True)

    height = f"(height: {yellow(str(chaininfo['blocks']))})"
    done(f"chain sync completed {height}      ", clear=True)
    delay()
    p()
    p()

    section("xpub import from Coldcard")
    delay()

    blank("now we're going to import your wallet's public information")
    blank("on your coldcard, go to Advanced > MicroSD > Dump Summary")
    blank("(see: https://coldcardwallet.com/docs/microsd#dump-summary-file)")
    p()
    delay()
    warn("this is not key material, but it can be used to track your addresses")
    p()
    delay()
    cwd = os.getcwd()
    task(f"place this file in this directory ({cwd})")
    delay()
    p()

    pubfilepath = Path("./public.txt")
    if not pubfilepath.exists():
        prompt = "would you like me to open a file explorer for you here? [Y/n] "
        if inp(prompt).lower() in ["y", ""]:
            open_file_browser()

    pubfile = None
    while not pubfile:
        spin("waiting for public.txt")
        time.sleep(0.1)
        if pubfilepath.exists():
            pubfile = pubfilepath

    try:
        wallet = controller.parse_cc_public(pubfile.read_text(), rpc)
    except Exception as e:
        p()
        if "key 'tpub" in str(e):
            warn("it looks like you're using a testnet config with a mainnet rpc.")
            warn("rerun this with `coldcore --rpc <testnet-rpc-url> setup`")
            sys.exit(1)
        if "key 'xpub" in str(e):
            warn("it looks like you're using a mainnet config with a testnet rpc.")
            warn("rerun this with `coldcore --rpc <mainnet-rpc-url> setup`")
            sys.exit(1)
        warn("error parsing public.txt contents")
        warn("check your public.txt file and try this again, or file a bug:")
        warn("  github.com/jamesob/coldcore/issues")
        p()
        traceback.print_exc()
        sys.exit(1)

    p()
    done("parsed xpub as ")
    blank(f"  {yellow(wallet.descriptor_base)}")
    p()

    walletname = inp(f"name of this wallet? [{wallet.name}] ")
    if walletname:
        wallet.name = walletname

    # Ensure we save the RPC connection we initialized with.
    wallet.bitcoind_json_url = rpc.url
    config.add_new_wallet(wallet)

    if use_gpg or config.loaded_from.startswith("pass:"):
        info(
            "writing wallet to encrypted config; GPG may prompt you "
            "for your password [press enter] "
        )
        input()

    config.write()
    done(f"wrote config to {config.loaded_from}")
    p()

    section("wallet setup in Core")
    controller.rpc_wallet_create(rpc, wallet)
    done(f"created wallet {yellow(wallet.name)} in Core as watch-only")

    rpcw = config.rpc(wallet)
    rpcw.importmulti(*wallet.importmulti_args())
    done("imported descriptors 0/* and 1/* (change)")

    scan_result = {}  # type: ignore
    scan_thread = threading.Thread(
        target=_run_scantxoutset,
        args=(config.rpc(wallet), wallet.scantxoutset_args(), scan_result),
    )
    scan_thread.start()

    p()
    section("scanning the chain for balance and history")
    while scan_thread.is_alive():
        spin("scanning the UTXO set for your balance (few minutes) ")
        time.sleep(0.2)

    p()
    done("scan of UTXO set complete!")

    # TODO this will fail if we timed out
    unspents = scan_result["result"]["unspents"]
    bal = sum([i["amount"] for i in unspents])
    bal_str = yellow(bold(f"{bal} BTC"))
    bal_count = yellow(bold(f"{len(unspents)} UTXOs"))
    blank(f"found an existing balance of {yellow(bal_str)} across {yellow(bal_count)}")

    if unspents:
        rescan_begin_height = min([i["height"] for i in unspents])
        p()
        blank(
            f"beginning chain rescan from height {bold(str(rescan_begin_height))} "
            f"(minutes to hours)"
        )
        blank("  this allows us to find transactions associated with your coins\n")
        rescan_thread = threading.Thread(
            target=_run_rescan,
            args=(config.rpc(wallet), rescan_begin_height),
            daemon=True,
        )
        rescan_thread.start()

        time.sleep(2)

    scan_info = rpcw.getwalletinfo()["scanning"]
    while scan_info:
        spin(f"scan progress: {scan_info['progress'] * 100:.2f}%   ")
        time.sleep(0.5)
        scan_info = rpcw.getwalletinfo()["scanning"]

    name = yellow(wallet.name)
    p()
    done(f"scan complete. wallet {name} ready to use.")
    info(f"Hint: check out your UTXOs with `coldcore -w {wallet.name} balance`")

    p()

    got = inp("do you want to perform some test transactions? [Y/n] ").lower()

    if got not in ["y", ""]:
        return finish(config, wallet)

    section("test transactions")

    receive_addr1 = rpcw.getnewaddress()
    task("send a tiny amount (we're talking like ~0.000001 BTC) to")
    p()
    blank(f"  {yellow(receive_addr1)}")
    p()
    blank("(obviously, this is an address you own)")
    p()

    got_utxo = None
    while not got_utxo:
        spin("waiting for transaction")
        utxos = controller.get_utxos(rpcw)
        matching = [u for u in utxos.values() if u.address == receive_addr1]
        if matching:
            got_utxo = matching[0]
        time.sleep(1)

    p()
    done(
        f"received amount of {green(str(got_utxo.amount))} "
        f"(txid {got_utxo.txid[:8]})"
    )
    p()

    info("great - now let's test your ability to send")
    info(
        "we're going to send 90% of the value of the last UTXO over "
        "to a new address:"
    )
    sendtoaddr = rpcw.getnewaddress()
    p()
    blank(f"  {yellow(sendtoaddr)}")
    p()

    # Send 90% of the value over.
    # TODO this is only for testing and is potentially dangerous
    send_amt = str(round(((got_utxo.amount * 9) / 10), 8))
    prepared_tx = controller.prepare_send(
        config,
        rpcw,
        sendtoaddr,
        send_amt,
        [got_utxo.address],
    )

    info(
        "I've prepared a transaction for you to sign in a "
        f"file called '{prepared_tx}'"
    )
    p()

    task("transfer this file to your Coldcard and sign it")
    p()
    warn(
        "as always, remember to verify all transaction details on the Coldcard "
        "display"
    )
    warn(
        "the Coldcard should say something like "
        "'Consolidating ... within wallet' when signing"
    )
    p()

    prompt = "would you like me to open a file explorer for you here? [Y/n] "
    if inp(prompt).lower() in ["y", ""]:
        open_file_browser()

    # TODO: coldcard specific?
    signed_filename = prepared_tx.replace(".psbt", "-signed.psbt")

    while not Path(signed_filename).exists():
        spin(f"waiting for the signed file ({signed_filename})")
        time.sleep(0.5)

    # TODO clean this up
    psbt_hex = base64.b64encode(Path(signed_filename).read_bytes()).decode()
    txhex = controller.psbt_to_tx_hex(rpcw, Path(signed_filename))
    p()
    p()
    done("cool! got the signed PSBT")

    if not controller.confirm_broadcast(rpcw, txhex, psbt_hex):
        warn("aborting - doublespend the inputs immediately")
        return finish(config, wallet)

    rpcw.sendrawtransaction(txhex)
    done("transaction broadcast!")
    p()

    inmempool = False
    while not inmempool:
        spin("waiting to see the transaction in the mempool")
        utxos = controller.get_utxos(rpcw)
        matching = [u for u in utxos.values() if u.address == sendtoaddr]
        if matching:
            got_utxo = matching[0]

        if got_utxo:
            inmempool = True

    p()
    done(f"saw tx {got_utxo.txid}")
    p()

    section("done")
    done(bold(f"your wallet {yellow(wallet.name)} is good to go"))
    p()
    p()

    return finish(config, wallet)


neversell = r"""
                                                                            $$\ $$\
                                                                            $$ |$$ |
$$$$$$$\   $$$$$$\ $$\    $$\  $$$$$$\   $$$$$$\         $$$$$$$\  $$$$$$\  $$ |$$ |
$$  __$$\ $$  __$$\\$$\  $$  |$$  __$$\ $$  __$$\       $$  _____|$$  __$$\ $$ |$$ |
$$ |  $$ |$$$$$$$$ |\$$\$$  / $$$$$$$$ |$$ |  \__|      \$$$$$$\  $$$$$$$$ |$$ |$$ |
$$ |  $$ |$$   ____| \$$$  /  $$   ____|$$ |             \____$$\ $$   ____|$$ |$$ |
$$ |  $$ |\$$$$$$$\   \$  /   \$$$$$$$\ $$ |            $$$$$$$  |\$$$$$$$\ $$ |$$ |
\__|  \__| \_______|   \_/     \_______|\__|            \_______/  \_______|\__|\__|

"""


def _run_scantxoutset(rpcw, args, result):
    try:
        result["result"] = rpcw.scantxoutset(*args)
    except socket.timeout:
        logger.debug("socket timed out during txoutsetscan (this is expected)")


def _run_rescan(rpcw, begin_height: int):
    try:
        rpcw.rescanblockchain(begin_height)
    except socket.timeout:
        logger.debug("socket timed out during rescan (this is expected)")


# Curses is weird and ENTER isn't always ENTER.
ENTER_KEYS = [curses.KEY_ENTER, 10, 13]


class HomeScene(Scene):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.dashboard_item = MenuItem(0, "dashboard", GoDashboard)
        self.setup_item = MenuItem(1, "set up wallet", GoSetup)
        # self.send_item = MenuItem(2, "send", GoHome)
        # self.recieve_item = MenuItem(3, "receive", GoHome)

        self.mitems = [
            self.setup_item,
            # self.send_item,
            # self.recieve_item,
        ]
        if self.wallet_configs:
            self.mitems.insert(0, self.dashboard_item)

        self.midx = 0
        self.mchoice = self.setup_item

    def draw(self, k: int) -> t.Tuple[int, Action]:
        scr = self.scr
        curses.noecho()
        height, width = scr.getmaxyx()
        wconfigs = self.wallet_configs

        if k in [ord("q")]:
            return (-1, Quit)
        elif k in ENTER_KEYS:
            return (-1, self.mchoice.action)

        if k in [curses.KEY_DOWN, ord("j")] and self.midx < (len(self.mitems) - 1):
            self.midx += 1
        elif k in [curses.KEY_UP, ord("k")] and self.midx > 0:
            self.midx -= 1

        self.mchoice = self.mitems[self.midx]

        # Declaration of strings

        title: str = """
░█████╗░░█████╗░██╗░░░░░██████╗░░█████╗░░█████╗░██████╗░███████╗
██╔══██╗██╔══██╗██║░░░░░██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝
██║░░╚═╝██║░░██║██║░░░░░██║░░██║██║░░╚═╝██║░░██║██████╔╝█████╗░░
██║░░██╗██║░░██║██║░░░░░██║░░██║██║░░██╗██║░░██║██╔══██╗██╔══╝░░
╚█████╔╝╚█████╔╝███████╗██████╔╝╚█████╔╝╚█████╔╝██║░░██║███████╗
░╚════╝░░╚════╝░╚══════╝╚═════╝░░╚════╝░░╚════╝░╚═╝░░╚═╝╚══════╝
    """

        titlelines = [i for i in title.splitlines() if i.strip()]
        title_len = len(titlelines[2])
        subtitle = "your monetary glue"

        # Centering calculations
        start_x_title = int((width // 2) - (title_len // 2) - title_len % 2)
        title_height = len(title.splitlines()) + 1
        start_y = height // 4

        if wconfigs:
            # TODO this will run off the end of the screen quickly
            keystr = f"Wallets: {', '.join([w.name for w in wconfigs])}".format(k)[
                : width - 1
            ]
            start_x_keystr = int((width // 2) - (len(keystr) // 2) - len(keystr) % 2)
            scr.addstr(start_y + title_height + 4, start_x_keystr, keystr[:width])

        start_x_subtitle = int((width // 2) - (len(subtitle) // 2) - len(subtitle) % 2)

        with attrs(scr, colr(2), curses.A_BOLD):
            for i, line in enumerate(titlelines):
                scr.addstr(start_y + i, start_x_title, line)

        scr.addstr(start_y + title_height, start_x_subtitle, subtitle[:width])
        scr.addstr(
            start_y + title_height + 2, start_x_title, ("/ " * (title_len // 2))[:width]
        )

        def menu_option(idx: int, text: str, selected=False):
            half = width // 2

            start_str = f'{"":<6}{text:>20}{"":<6}'
            if selected:
                start_str = " -> " + start_str[4:]
            scr.addstr(start_y + title_height + 8 + idx, half, start_str[:width])

        if self.wallet_configs:
            menu_option(*self.dashboard_item.args(self.mchoice))
            # TODO
            # menu_option(*self.send_item.args(self.mchoice))
            # menu_option(*self.recieve_item.args(self.mchoice))

        menu_option(*self.setup_item.args(self.mchoice))

        scr.move(0, 0)

        # Refresh the screen
        scr.refresh()

        k = scr.getch()
        # Wait for next input
        return (k, GoHome)


def _s(window, y, x, msg, attr=0):
    """A width-safe version of addstr."""
    (_, width) = window.getmaxyx()
    if not attr:
        window.addstr(y, x, msg[:width])
    else:
        window.addstr(y, x, msg[:width], attr)


class DashboardScene(Scene):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.utxos = {}
        self.threads = []
        self.threads_started = False
        self.new_addrs = []
        self.blocks = []

        self.conn_status = None
        self.loop_count = 0
        self.cursorposx = 0
        self.flash_msg = ""
        self.selected_utxos = set()

        # Y cursor positions within each window.
        self.wincursoridx = {
            "utxos": 0,
            "addrs": 0,
        }

    def start_threads(self):
        if self.threads_started:
            return

        wall = self.wallet_configs[0]
        wrpc = self.config.rpc(wall, timeout=2)

        t1 = threading.Thread(
            target=_get_utxo_lines,
            args=(wrpc, self.controller, self.utxos),
        )
        t1.start()
        self.threads.append(t1)

        t2 = threading.Thread(
            target=_get_new_blocks,
            args=(self.config.rpc(timeout=2), self.blocks),
        )
        t2.start()
        self.threads.append(t2)

        self.threads_started = True
        self.rpc = self.config.rpc()

    def stop_threads(self):
        stop_threads_event.set()
        for thread in self.threads:
            thread.join()

    def draw(self, k: int) -> t.Tuple[int, Action]:
        try:
            return self._draw(k)
        except Exception:
            logger.exception("Dashboard curses barfed")
            self.stop_threads()
            raise

        return (ord("q"), GoHome)

    def _draw(self, k: int) -> t.Tuple[int, Action]:
        scr = self.scr
        self.height, self.width = scr.getmaxyx()
        wall = self.wallet_configs[0]

        substartx = 3
        substarty = 2
        top_panel_height = int(self.height * 0.7)

        balwidth = max(int(self.width * 0.6) - 4, 66)
        addrwidth = max(int(self.width * 0.4) - 2, 26)
        chainwidth = max(self.width - 6, 92)
        chainwin_height = int(self.height * 0.25)

        self.balance_win = scr.derwin(top_panel_height, balwidth, substarty, substartx)
        self.address_win = scr.derwin(
            top_panel_height, addrwidth, substarty, substartx + balwidth + 1
        )
        self.chain_win = scr.derwin(
            chainwin_height, chainwidth, substarty + top_panel_height, substartx
        )

        LIMIT_NEW_ADDRS = 10

        if k != -1:
            self.flash_msg = ""

        if rpc_conn_lost.is_set():
            self.flash_msg = "connection to Bitcoin Core lost"

        if k == ord("n"):
            if len(self.new_addrs) < LIMIT_NEW_ADDRS:
                try:
                    rpcw = self.config.rpc(wall)
                    self.new_addrs.append(rpcw.getnewaddress())
                except Exception:
                    logger.info("call to getnewadddress failed", exc_info=True)

        utxo_addrs = {u.address for u in self.utxos.values()}
        # Strip out used addresses.
        self.new_addrs = [a for a in self.new_addrs if a not in utxo_addrs]

        with utxos_lock:
            utxos = dict(self.utxos)

        max_balance_utxo_lines = self.balance_win.getmaxyx()[0] - 6
        total_balance_lines = min(len(utxos), max_balance_utxo_lines)

        # The (window name, y pos) of the user's selection cursor.
        if k in [ord("h"), curses.KEY_LEFT, ord("a")] and self.cursorposx > 0:
            self.cursorposx -= 1
        elif k in [ord("l"), curses.KEY_RIGHT, ord("d")] and self.cursorposx < 1:
            self.cursorposx += 1

        cur_win_title = [
            "utxos",
            "addrs",
        ][self.cursorposx]
        last_wincursoridx = self.wincursoridx[cur_win_title]

        downkeys = [ord("j"), curses.KEY_DOWN, ord("s")]
        upkeys = [ord("k"), curses.KEY_UP, ord("w")]

        if cur_win_title == "utxos":
            if k in downkeys and last_wincursoridx < (total_balance_lines - 1):
                self.wincursoridx["utxos"] += 1
            elif k in upkeys and last_wincursoridx > 0:
                self.wincursoridx["utxos"] -= 1

        elif cur_win_title == "addrs":
            if k in downkeys and last_wincursoridx < (len(self.new_addrs) - 1):
                self.wincursoridx["addrs"] += 1
            elif k in upkeys and last_wincursoridx > 0:
                self.wincursoridx["addrs"] -= 1

        # Bring cursor to new address if created
        if k == ord("n"):
            cur_win_title = "addrs"
            self.cursorposx = 1  # the index for the addresses window
            self.wincursoridx[cur_win_title] = len(self.new_addrs) - 1

        wincursoridx = self.wincursoridx[cur_win_title]

        try:
            self.start_threads()
        except ConnectionRefusedError:
            curses.endwin()
            F.warn("Unable to connect to Bitcoin Core RPC")
            F.warn("Ensure Core is running or use `coldcore --rpc <url>`")
            sys.exit(1)

        # --- Paint the balances window

        border_attrs = [curses.A_BOLD] if cur_win_title == "utxos" else []
        title_attrs = [curses.A_STANDOUT] if cur_win_title == "utxos" else []
        with attrs(self.balance_win, *border_attrs):
            self.balance_win.border()
        with attrs(self.balance_win, *title_attrs):
            _s(self.balance_win, 0, 2, " UTXOs ")

        _s(
            self.balance_win,
            2,
            2,
            f"{'address':<48}{'confs':>10}{'BTC':>12}",
        )

        starty = 2
        startx = 2

        _s(self.balance_win, starty, startx, "")
        starty += 1

        if max_balance_utxo_lines < len(utxos):
            _s(
                self.balance_win,
                starty,
                startx,
                "-- too many UTXOs to fit --",
                curses.A_BOLD,
            )
            starty += 1

        sorted_utxos = sorted(utxos.values(), key=lambda u: -u.num_confs)[
            -max_balance_utxo_lines:
        ]
        total_bal = f"{sum([u.amount for u in sorted_utxos])}"
        coin_idx = 0
        y_idx = 0

        def sanitize_label(label: str):
            return "".join(i for i in label if i in string.printable).strip()

        bal_line_width = 70

        for u in sorted_utxos:
            attrslist = []

            if u.num_confs < 6:
                attrslist.extend([colr(6), curses.A_BOLD])

            enter_label = False

            if cur_win_title == "utxos" and wincursoridx == coin_idx:
                attrslist.append(curses.A_REVERSE)

                if k in (ENTER_KEYS + [ord(" ")]):
                    # Enter pressed; toggle this address for spending
                    self.selected_utxos ^= {u.id}
                elif k == ord("L"):
                    enter_label = True

            addr_str = u.address
            if u.id in self.selected_utxos:
                attrslist.append(colr(4))
                addr_str = f"✔ {addr_str}"

            line = f"{addr_str:<48}{u.num_confs:>10}{u.amount:>12}"

            with attrs(self.balance_win, *attrslist):
                _s(self.balance_win, starty + y_idx, startx, line)

                coin_idx += 1
                y_idx += 1

                if u.label:
                    label = sanitize_label(u.label)
                    if len(label) > (balwidth - 4):
                        label = label[: (balwidth - 7)] + "..."
                    label += " " * (bal_line_width - len(label) - 4)
                    _s(self.balance_win, starty + y_idx, startx, f" └─ {label}")
                    y_idx += 1

            if enter_label:
                _s(self.balance_win, starty + y_idx, startx + 1, "Enter label")
                labelwin = self.balance_win.derwin(
                    1, balwidth - startx - 5, starty + y_idx + 1, startx + 1
                )
                _s(labelwin, 0, 0, " └─ ")

                tb = Textbox(labelwin)
                scr.refresh()
                tb.edit()
                new_label = sanitize_label(tb.gather())

                try:
                    rpcw = self.config.rpc(wall)
                    rpcw.setlabel(u.address, new_label)
                except Exception:
                    logger.info("failed to set label", exc_info=True)
                    self.flash_msg = "failed to set label"
                else:
                    self.flash_msg = f"set label to '{new_label}'"
                # Redraw with label
                return (-1, GoDashboard)

        if sorted_utxos:
            _s(
                self.balance_win,
                starty + y_idx + 1,
                startx,
                f"{' ':<54}{total_bal:>16}",
                curses.A_BOLD,
            )

        # --- Paint the addresses window

        border_attrs = [curses.A_BOLD] if cur_win_title == "addrs" else []
        title_attrs = [curses.A_STANDOUT] if cur_win_title == "addrs" else []
        with attrs(self.address_win, *border_attrs):
            self.address_win.border()
        with attrs(self.address_win, *title_attrs):
            _s(self.address_win, 0, 2, " unused addresses ")

        _s(self.address_win, 2, 2, "press 'n' to get new address")

        for i, addr in enumerate(self.new_addrs):
            attrslist = []
            is_highlighted = cur_win_title == "addrs" and wincursoridx == i

            if is_highlighted:
                attrslist.append(curses.A_REVERSE)

            with attrs(self.address_win, *attrslist):
                _s(self.address_win, 3 + i, 2, addr)

            if is_highlighted and k in ENTER_KEYS:
                to_clipboard(addr)
                self.flash_msg = f"copied address '{addr}' to clipboard"

        # --- Paint the chain history window

        self.chain_win.box()
        _s(self.chain_win, 0, 2, " chain status ")

        max_history = chainwin_height - 5

        if not self.conn_status or self.loop_count % 20 == 0:
            try:
                rpc = self.config.rpc()
                netinfo = self.rpc.getnetworkinfo()
            except Exception:
                self.conn_status = "! couldn't connect to Bitcoin Core"
            else:
                ver = netinfo["subversion"].strip("/")
                self.conn_status = (
                    f"✔ connected to version {ver} at {rpc.host}:{rpc.port}"
                )

        status_attrs = [curses.A_BOLD, colr(2)] if self.conn_status[0] == "!" else []
        with attrs(self.chain_win, *status_attrs):
            _s(self.chain_win, 2, 3, self.conn_status)

        with blocks_lock:
            for i, b in enumerate(self.blocks[-max_history:]):
                blockstr = (
                    f"{b.time_saw} | block {b.height} (...{b.hash[-8:]}) - "
                    f"{b.median_fee} sat/B - "
                    f"{b.txs} txs - "
                    f"subsidy: {b.subsidy / 100_000_000}"
                )
                _s(self.chain_win, 4 + i, 3, blockstr[:chainwidth])

        if self.flash_msg:
            with attrs(scr, colr(3)):
                msg = f" (!) {self.flash_msg}"
                msg = msg + (" " * (self.width - len(msg) - 1))
                scr.addstr(0, 0, msg)

        scr.refresh()

        # scr.move(self.width, self.height)

        scr.timeout(400)
        next_k = scr.getch()
        self.loop_count += 1

        if next_k == ord("q"):
            self.stop_threads()

        return (next_k, GoDashboard)


def to_clipboard(s: str) -> bool:
    """Put s into the system clipboard."""
    plat = platform.system()

    def sh(cmd, **kwargs) -> int:
        return subprocess.run(cmd, shell=True, **kwargs).returncode

    if plat == "Linux":
        if sh("which xclip", capture_output=True) != 0:
            logger.info("xclip not found, cannot copy to clipboard")
            return False
        cmd = "xclip -selection clipboard"
        sh(f"printf '{s}' | {cmd}")
    elif plat == "Darwin":
        cmd = "pbcopy"
        sh(f"printf '{s}' | {cmd}")
    elif plat == "Windows":
        cmd = "clip"
        sh(f"echo {s} | {cmd}")

    return True


@dataclass
class Block:
    hash: str
    height: int
    time_saw: datetime.datetime
    median_fee: float
    subsidy: float
    txs: int


rpc_conn_lost = threading.Event()
stop_threads_event = threading.Event()
utxos_lock = threading.Lock()
blocks_lock = threading.Lock()


def _get_new_blocks(rpc, blocks):
    last_saw = None

    while True:
        try:
            saw = rpc.getbestblockhash()
        except Exception:
            logger.info("getbestblockhash call failed", exc_info=True)
            rpc_conn_lost.set()

        if saw != last_saw:
            stats = rpc.getblockstats(saw)
            with blocks_lock:
                blocks.append(
                    Block(
                        saw,
                        stats["height"],
                        datetime.datetime.now(),
                        stats["feerate_percentiles"][2],
                        stats["subsidy"],
                        stats["txs"],
                    )
                )
            last_saw = saw

        rpc_conn_lost.clear()
        time.sleep(1)

        if stop_threads_event.is_set():
            return


def _get_utxo_lines(rpcw, controller, utxos):
    """
    Poll constantly for new UTXOs.
    """
    while True:
        try:
            new_utxos = controller.get_utxos(rpcw)
        except Exception:
            logger.info("listunspents call failed", exc_info=True)

        with utxos_lock:
            utxos.clear()
            utxos.update(new_utxos)

        time.sleep(1)

        if stop_threads_event.is_set():
            return


GoHome = Action()
GoSetup = Action()
GoDashboard = Action()
Quit = Action()


class _TermOpts:
    has_256color = False


TermOpts = _TermOpts()


def draw_menu(scr, config, wallet_configs, controller, action=None):
    wallet_configs = wallet_configs or []
    # Clear and refresh the screen for a blank canvas
    scr.clear()
    scr.refresh()
    scr.scrollok(True)

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    if curses.COLORS >= 256:
        TermOpts.has_256color = True

    home = HomeScene(scr, config, wallet_configs, controller)
    dashboard = DashboardScene(scr, config, wallet_configs, controller)

    action = action or GoHome
    k = 0

    while action != Quit:
        # Initialization
        scr.clear()
        height, width = scr.getmaxyx()

        try:
            kstr = curses.keyname(k).decode()
        except ValueError:
            kstr = "???"

        statusbarstr = f"press 'q' to exit | never sell | last keypress: {kstr} ({k})"
        if k == -1:
            statusbarstr += " | waiting"

        try:
            # Render status bar
            with attrs(scr, colr(3)):
                try:
                    scr.addstr(height - 1, 0, statusbarstr[:width])
                    scr.addstr(
                        height - 1,
                        len(statusbarstr),
                        (" " * (width - len(statusbarstr) - 1))[:width],
                    )
                    # TODO better status bar
                except Exception:
                    pass

            if action == GoHome:
                (k, action) = home.draw(k)
            elif action == GoSetup:
                config, wallet = run_setup(config, controller)
                # Reinitialize the scenes
                if config and wallet:
                    wallet_configs.append(wallet)
                    home = HomeScene(scr, config, wallet_configs, controller)
                    dashboard = DashboardScene(scr, config, wallet_configs, controller)
                k = -1
                action = GoHome
            elif action == GoDashboard:
                (k, action) = dashboard.draw(k)
        except curses.error:
            scr = curses.initscr()
            scr.clear()
            scr.timeout(400)
            scr.refresh()
            scr.addstr(1, 1, "! terminal too small.")
            scr.addstr(2, 1, "! resize to make larger")
            scr.addstr(3, 1, "! or press 'q' to exit.")
            scr.refresh()
            time.sleep(0.3)
            k = scr.getch()

        if k == ord("q") or action == Quit:
            break


@contextlib.contextmanager
def attrs(scr, *attrs):
    for a in attrs:
        scr.attron(a)
    yield
    for a in attrs:
        scr.attroff(a)


def start_ui(config, wallet_configs, controller, action=None):
    formatter = OutputFormatter()
    try:
        curses.wrapper(draw_menu, config, wallet_configs, controller, action)
        os.system("cls" if os.name == "nt" else "clear")
    except curses.error:
        print()
        formatter.warn("The UI crashed! Terminal might be too small, try resizing.")
        print()
        sys.exit(1)
    except socket.timeout:
        logger.exception("RPC connection timed out")
        print()
        formatter.warn("Unable to connect to Bitcoin Core RPC - are you sure ")
        formatter.warn("it is running and the RPC URL you gave is correct?")
        formatter.alert("See `--rpc` in `coldcore --help`")
        print()
        sys.exit(1)
