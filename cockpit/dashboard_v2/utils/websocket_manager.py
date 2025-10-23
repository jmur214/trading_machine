from __future__ import annotations
import asyncio
import threading
from queue import Queue

try:
    from alpaca.trading.stream import TradingStream
except Exception:
    TradingStream = None

class AlpacaStreamManager:
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        self.queue = Queue()
        self.thread = None
        self.running = False
        self.stream = None

    def start(self):
        if TradingStream is None:
            print("[WS] Alpaca TradingStream unavailable (alpaca-py missing)."); return
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                asyncio.run_coroutine_threadsafe(self.stream.stop(), asyncio.get_event_loop())
            except Exception:
                pass

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._main())

    async def _main(self):
        try:
            if TradingStream is None:
                print("[WS] Alpaca TradingStream unavailable.")
                return

            self.stream = TradingStream(self.api_key, self.api_secret, paper=self.paper)
            print("[WS] Connecting to Alpaca TradingStream...")

            async def on_account(data):
                self.queue.put({"type": "account", "data": data})

            async def on_trade(data):
                self.queue.put({"type": "trade", "data": data})

            # --- Subscribe to updates (API version–agnostic) ---
            subscribed = False

            # Try trade updates
            for name in ["subscribe_trade_updates", "subscribe_trades", "subscribe_trade_stream"]:
                if hasattr(self.stream, name):
                    try:
                        getattr(self.stream, name)(on_trade)
                        subscribed = True
                        print(f"[WS] Subscribed to trades via {name}()")
                        break
                    except Exception as e:
                        print(f"[WS] Could not subscribe via {name}: {e}")

            # Try account updates
            for name in ["subscribe_account_updates", "subscribe_accounts", "subscribe_account_stream"]:
                if hasattr(self.stream, name):
                    try:
                        getattr(self.stream, name)(on_account)
                        subscribed = True
                        print(f"[WS] Subscribed to account updates via {name}()")
                        break
                    except Exception as e:
                        print(f"[WS] Could not subscribe via {name}: {e}")

            if not subscribed:
                print("[WS] No matching subscription methods found for this Alpaca SDK version.")

            if hasattr(self.stream, "_run_forever") and asyncio.iscoroutinefunction(self.stream._run_forever):
                await self.stream._run_forever()
            else:
                await asyncio.to_thread(self.stream.run)

        except Exception as e:
            print(f"[WS] Stream error: {e}")