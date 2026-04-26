"""
visualizer.py — minimal Flask SSE oscilloscope
"""
import mmap, struct, time, json
from flask import Flask, Response, render_template

FILE_PATH   = "/tmp/live_data.mmap"
SLOT_SIZE   = 64
N_SLOTS     = 4096
HEADER_SIZE = 8
RECORD_FMT  = "d d i"

app = Flask(__name__)

fh = None
mm = None

def get_mmap():
    global fh, mm
    if mm is None:
        fh = open(FILE_PATH, "r+b")
        mm = mmap.mmap(fh.fileno(), 0)
    return mm

def stream():
    mm = get_mmap()
    own_head = struct.unpack_from("Q", mm, 0)[0]
    while True:
        write_head = struct.unpack_from("Q", mm, 0)[0]
        batch = []
        while own_head < write_head:
            slot   = own_head % N_SLOTS
            offset = HEADER_SIZE + slot * SLOT_SIZE
            ts, value, flags = struct.unpack_from(RECORD_FMT, mm, offset)
            batch.append({"t": round(ts,4), "v": round(value, 5), "f": flags})
            own_head += 1
        if batch:
            yield f"data: {json.dumps(batch)}\n\n"
        time.sleep(0.016)

@app.route("/stream")
def stream_route():
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    print("http://localhost:5000")
    app.run(debug=False, threaded=True, port=5000)
