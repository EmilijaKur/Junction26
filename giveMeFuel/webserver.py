import time

from flask import Flask, Response
#from arduino.app_utils import *

from src.cammera import Camera

app = Flask(__name__)
camera = Camera(index="/dev/v4l/by-id/usb-HHWei_Technology_Co.__Ltd._Web_Camera_HHW006-video-index0")

PAGE = """
<html>
  <head><title>Fire node camera</title></head>
  <body style="background:#111;color:white;text-align:center;font-family:sans-serif">
    <h2>Fire node camera</h2>
    <img src="/video_feed" style="max-width:100%;height:auto"/>
    <div>
    <table>
        <thead>
            <tr>
                <th>Sensor / metric</th>
                <th>Reading</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Classification</td>
                <td id="classification">None</td>
            </tr>
            <tr>
                <td>Temperature</td>
                <td id="temperature">-</td>
            </tr>
            <tr>
                <td>Humidity</td>
                <td id="humidity">-</td>
            </tr>
        </tbody>
    </table>
  </div>  
  </body>
</html>
"""

#def alert_matei():
#    result = Bridge.call("alert-matei")



def generate():
    while True:
        jpeg = camera.get_jpeg()
        if jpeg is None:
            time.sleep(0.05)
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.03)  # about 30 fps cap

def main_loop():
    while True:
        jpeg, classification, confidence = camera.get_jpeg()

        if jpeg is None:
            time.sleep(0.05)
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.03)
        print(classification, confidence)  

 #       matei_results = Bridge.call("get-stuff")

 #       ugnes_fire_logic(classification, confidence, matei_results)


@app.route("/")
def index():
    return PAGE


@app.route("/video_feed")
def video_feed():
    return Response(main_loop(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
