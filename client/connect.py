"""
BBS Test Client.
Connects to the BBS server via telnet and provides an interactive session.
Can also run automated connection tests.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.telnet_protocol import TelnetNegotiator, IAC, DO, WILL, DONT, WONT


class BBSClient:
    """Telnet client that connects to the BBS server."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 6400):
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.negotiator = TelnetNegotiator()
        self._connected = False
    
    async def connect(self):
        """Connect to the BBS server."""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self._connected = True
            print(f"Connected to {self.host}:{self.port}")
            return True
        except ConnectionRefusedError:
            print(f"Connection refused: {self.host}:{self.port}")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the server."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass
        self._connected = False
    
    async def send_input(self, text: str):
        """Send user input to the server."""
        if not self._connected or not self.writer:
            return
        data = text.encode('latin-1', errors='replace')
        self.writer.write(data)
        await self.writer.drain()
    
    async def receive_output(self, timeout: float = 2.0) -> str:
        """
        Receive and process output from the server.
        Reads in a loop to accumulate both negotiation bytes and content.
        Returns only the clean (non-telnet) text content.
        """
        if not self._connected or not self.reader:
            return ""
        
        clean_output = bytearray()
        deadline = asyncio.get_event_loop().time() + timeout
        got_content = False
        
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            
            try:
                data = await asyncio.wait_for(
                    self.reader.read(4096),
                    timeout=min(remaining, 0.5)
                )
            except asyncio.TimeoutError:
                break
            except (ConnectionResetError, BrokenPipeError, OSError):
                self._connected = False
                break
            
            if not data:
                self._connected = False
                return "[Disconnected]"
            
            # Process through telnet negotiator
            clean_data, responses = self.negotiator.process_data(data)
            
            # Respond to server negotiations
            if responses and self.writer:
                for resp in responses:
                    self.writer.write(resp)
                await self.writer.drain()
            
            # Accumulate clean content
            if clean_data:
                clean_output.extend(clean_data)
                got_content = True
                # Once we have content, do one more read to catch anything
                # still in the pipe, then return
                try:
                    more = await asyncio.wait_for(
                        self.reader.read(4096),
                        timeout=0.3
                    )
                    if more:
                        clean_data2, responses2 = self.negotiator.process_data(more)
                        if responses2 and self.writer:
                            for resp in responses2:
                                self.writer.write(resp)
                            await self.writer.drain()
                        if clean_data2:
                            clean_output.extend(clean_data2)
                except asyncio.TimeoutError:
                    pass
                except (ConnectionResetError, BrokenPipeError, OSError):
                    self._connected = False
                    break
                break
        
        return clean_output.decode('latin-1', errors='replace')
    
    async def interactive(self):
        """Run an interactive session."""
        if not await self.connect():
            return
        
        print("\n--- Interactive BBS Session ---")
        print("Type your input and press Enter. Type 'quit' to disconnect.\n")
        
        # Start a task to read output
        async def read_loop():
            while self._connected:
                output = await self.receive_output(timeout=0.5)
                if output:
                    sys.stdout.write(output)
                    sys.stdout.flush()
        
        # Start reader task
        read_task = asyncio.create_task(read_loop())
        
        try:
            loop = asyncio.get_event_loop()
            
            # Use the event loop's stdin reader
            while self._connected:
                try:
                    # Read a line from stdin
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    
                    line = line.rstrip('\n')
                    if line.lower() == 'quit':
                        break
                    
                    await self.send_input(line + '\r\n')
                except (EOFError, KeyboardInterrupt):
                    break
        finally:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass
            await self.disconnect()
            print("\nDisconnected.")


async def connection_test(host: str = "127.0.0.1", port: int = 6400):
    """
    Automated connection test.
    Connects, receives banner, sends a choice, verifies response.
    """
    print(f"=== BBS Connection Test ===")
    print(f"Target: {host}:{port}\n")
    
    client = BBSClient(host, port)
    
    # Test 1: Connect
    print("Test 1: TCP Connection...")
    if not await client.connect():
        print("  FAIL: Could not connect")
        return False
    print("  PASS: Connected")
    
    # Test 2: Receive banner
    print("\nTest 2: Receive banner...")
    output = await client.receive_output(timeout=3.0)
    if output and ("MODULO" in output or "BBS" in output or "Welcome" in output or "Login" in output):
        print("  PASS: Banner received")
        # Show first few lines
        lines = output.strip().split('\n')
        for line in lines[:8]:
            print(f"  | {line.rstrip()}")
        if len(lines) > 8:
            print(f"  | ... ({len(lines)} lines total)")
    else:
        print(f"  FAIL: No banner (got: {repr(output[:100])})")
        await client.disconnect()
        return False
    
    # Test 3: Send menu choice
    print("\nTest 3: Send menu choice '3' (System Info)...")
    await client.send_input("3\r\n")
    output = await client.receive_output(timeout=2.0)
    if output and "System Information" in output:
        print("  PASS: System Info displayed")
        lines = output.strip().split('\n')
        for line in lines[:8]:
            print(f"  | {line.rstrip()}")
    else:
        print(f"  FAIL: No system info (got: {repr(output[:100])})")
    
    # Test 4: Terminal negotiation
    print("\nTest 4: Terminal Negotiation...")
    neg = client.negotiator
    print(f"  Terminal type: {neg.terminal_type}")
    print(f"  Window size: {neg.window_size}")
    print(f"  Remote options: {list(neg.remote_options.keys())}")
    print(f"  Local options: {list(neg.local_options.keys())}")
    if neg.remote_options or neg.local_options:
        print("  PASS: Negotiation occurred")
    else:
        print("  WARN: No options negotiated (server may not have responded)")
    
    # Test 5: Send quit
    print("\nTest 5: Disconnect...")
    await client.send_input("Q\r\n")
    output = await client.receive_output(timeout=1.0)
    if output and "Goodbye" in output:
        print("  PASS: Clean disconnect")
    else:
        print(f"  INFO: Disconnect response: {repr(output[:100])}")
    
    await client.disconnect()
    
    print("\n=== All Tests Complete ===")
    return True


async def main():
    """Main entry point for the client."""
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        host = "127.0.0.1"
        port = 6400
        
        if '--host' in sys.argv:
            idx = sys.argv.index('--host')
            host = sys.argv[idx + 1]
        if '--port' in sys.argv:
            idx = sys.argv.index('--port')
            port = int(sys.argv[idx + 1])
        
        success = await connection_test(host, port)
        sys.exit(0 if success else 1)
    else:
        host = "127.0.0.1"
        port = 6400
        
        if '--host' in sys.argv:
            idx = sys.argv.index('--host')
            host = sys.argv[idx + 1]
        if '--port' in sys.argv:
            idx = sys.argv.index('--port')
            port = int(sys.argv[idx + 1])
        
        client = BBSClient(host, port)
        await client.interactive()


if __name__ == "__main__":
    asyncio.run(main())
