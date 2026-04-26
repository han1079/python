import mmap, struct, time, math, random, os

FILE_PATH   = "/tmp/live_data.mmap"
SLOT_SIZE   = 64
N_SLOTS     = 4096
HEADER_SIZE = 8
RECORD_FMT  = "d d i"   # timestamp, value, channel

total = HEADER_SIZE + SLOT_SIZE * N_SLOTS

FLAG_NEW_SESSION = 1 << 0

if not os.path.exists(FILE_PATH):
# Writes it full of zeros. Conveniently, this also makes
# the "head" address a zero - which allows the ring to start
# at zero.
    with open(FILE_PATH, "wb") as f:
        f.write(b'\x00' * total)



fpth = open(FILE_PATH, "r+b")
mm = mmap.mmap(fpth.fileno(), 0)

t0, tick = time.time(), 0
head   = struct.unpack_from("Q", buffer=mm, offset=0)[0]

new_start = True
STATE = 0 

def set_flag(state, flag): return state | flag 
def clear_flag(state, flag): return state & ~flag 
def check_flag(state, flag): return bool(state & flag)

while True:
    if new_start:
        STATE = set_flag(STATE, FLAG_NEW_SESSION)
        new_start = False

    now     = time.time()
    elapsed = now - t0
    value   = math.sin(2 * math.pi * 2 * elapsed) + random.gauss(0, 0.1)
    print(f"\rGenerated: {value}", end="", flush=True)


    head   = struct.unpack_from("Q", buffer=mm, offset=0)[0]
    offset = HEADER_SIZE + (head % N_SLOTS) * SLOT_SIZE
    struct.pack_into(RECORD_FMT, mm, offset, now, value, STATE)
    struct.pack_into("Q", mm, 0, head + 1)
    mm.flush()

    tick += 1
    time.sleep(max(0, t0 + tick * 0.01 - time.time()))
