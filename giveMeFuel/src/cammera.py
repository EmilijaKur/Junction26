import ast
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

MODEL_PATH = Path(__file__).resolve().parent / "best_detect.onnx"
sess = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
_inp = sess.get_inputs()[0]
S = _inp.shape[2]  
NAMES = ast.literal_eval(sess.get_modelmeta().custom_metadata_map["names"])


def detect(frame, conf_threshold=0.5, nms_threshold=0.45):
    h_orig, w_orig = frame.shape[:2]

    blob = cv2.resize(frame, (S, S))
    blob = blob[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    out = sess.run(None, {_inp.name: blob})[0]   
    preds = out[0].T                             

    
    class_scores = preds[:, 4:]
    class_ids = class_scores.argmax(1)
    scores = class_scores.max(1)

    keep = scores > conf_threshold
    preds, scores, class_ids = preds[keep], scores[keep], class_ids[keep]
    if len(scores) == 0:
        return []

    x_scale, y_scale = w_orig / S, h_orig / S
    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    x1 = (cx - w / 2) * x_scale
    y1 = (cy - h / 2) * y_scale
    boxes = np.stack([x1, y1, w * x_scale, h * y_scale], 1).astype(int).tolist()

    indices = cv2.dnn.NMSBoxes(boxes, scores.tolist(), conf_threshold, nms_threshold)

    results = []
    for i in np.array(indices).flatten():
        results.append({
            "box": boxes[i],
            "score": float(scores[i]),
            "class_id": int(class_ids[i]),
            "label": NAMES[int(class_ids[i])],
        })
    return results


class Camera:
    """Reads frames from a USB camera in a background thread."""

    def __init__(self, index=2, width=640, height=480):
        self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 15)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {index}")

        self._frame = None
        self._detections = []
        self._classification = "none"
        self._confidence = 0.0
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            try:
                detections = detect(frame, conf_threshold=0.6)
            except Exception as e:
                print("inference failed:", e)
                time.sleep(0.05)
                continue

            for det in detections:
                x, y, w, h = det["box"]
                label, score = det["label"], det["score"]

                if label == "fire":
                    color = (255, 165, 0)
                elif label == "smoke":
                    color = (0, 165, 255)
                else:
                    color = (0, 255, 0)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, f"{label}: {score:.1%}", (x, max(20, y - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            top = max(detections, key=lambda d: d["score"]) if detections else None

            with self._lock:
                self._frame = frame
                self._detections = detections
                self._classification = top["label"] if top else "none"
                self._confidence = top["score"] if top else 0.0

    def get_frame(self):
        """Latest frame as a BGR numpy array, or None if none yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self, quality=80):
        """Returns (jpeg_bytes, classification, confidence), or None."""
        with self._lock:
            if self._frame is None:
                return None
            frame = self._frame.copy()
            classification = self._classification
            confidence = self._confidence

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return (buf.tobytes(), classification, confidence) if ok else None

    def release(self):
        self._running = False
        self.cap.release()
