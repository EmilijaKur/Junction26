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
S = _inp.shape[2]  # fixed input size from the export, e.g. 224
NAMES = ast.literal_eval(sess.get_modelmeta().custom_metadata_map["names"])

'''def classify(frame):
    h, w = frame.shape[:2]
    r = S / min(h, w)                                   # resize short side to S
    f = cv2.resize(frame, (round(w * r), round(h * r)))
    y0, x0 = (f.shape[0] - S) // 2, (f.shape[1] - S) // 2
    crop = f[y0:y0 + S, x0:x0 + S]                      # center crop
    blob = crop[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255
    probs = sess.run(None, {_inp.name: blob})[0][0]
    i = int(probs.argmax())
    return NAMES[i], float(probs[i])
'''

# --- NEW DETECTION FUNCTION ---
def detect(frame, conf_threshold=0.5):
    h_orig, w_orig = frame.shape[:2]
    
    # Preprocess: resize frame to model input size and normalize
    blob = cv2.resize(frame, (S, S))
    blob = blob[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    
    # Run ONNX inference
    outputs = sess.run(None, {_inp.name: blob})[0]  # Shape: (1, 6, 2100)
    outputs = outputs.transpose(0, 2, 1)          # Shape: (1, 2100, 6)
    predictions = outputs[0]                      # Shape: (2100, 6)
    
    boxes, scores, class_ids = [], [], []
    x_scale = w_orig / S
    y_scale = h_orig / S
                
    for pred in predictions:
        confidence = float(pred[4])
        if confidence > conf_threshold:
            class_scores = pred[5:]
            class_id = int(np.argmax(class_scores))
            class_score = float(class_scores[class_id])
            
            score = confidence * class_score
            if score > conf_threshold:
                cx, cy, w, h = pred[0], pred[1], pred[2], pred[3]
                
                # Convert center coordinates to top-left bounding box format
                x1 = int((cx - w / 2) * x_scale)
                y1 = int((cy - h / 2) * y_scale)
                x2 = int((cx + w / 2) * x_scale)
                y2 = int((cy + h / 2) * y_scale)
                
                boxes.append([x1, y1, x2 - x1, y2 - y1])
                scores.append(score)
                class_ids.append(class_id)

    # Filter overlapping boxes with Non-Maximum Suppression
    indices = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=conf_threshold, nms_threshold=0.45)
             
    results = []
    if len(indices) > 0:
        for i in indices.flatten():
            results.append({
                "box": boxes[i],
                "score": scores[i],
                "class_id": class_ids[i],
                "label": NAMES[class_ids[i]]
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
        self._lock = threading.Lock()
        self._classification = None
        self._confidence = None
        self._running = True
        threading.Thread(target=self._reader, daemon=True).start()
                 
    def _reader(self):
    	while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            '''label, confidence = classify(frame)          # outside the lock
            self.classification = label
            self.confidence = confidence
            color = (0, 0, 255) if label == "fire" and confidence > 0.7 else (0, 255, 0)
            cv2.putText(frame, f"{label}: {confidence:.1%}", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
            '''
            detections = detect(frame, conf_threshold=0.6)
            self._detections = detections
	        for det in detections:
                x, y, w, h = det["box"]
                label = det["label"]
                score = det["score"]
		        if label == "fire":
                    color = (255, 0, 0)
                elif label == "smoke":
                    color = (0, 165, 255)
                else:
                    color = (0, 255, 0)
                
                # Draw the bounding box rectangle
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                
                # Draw the label text above the box
                text = f"{label}: {score:.1%}"
                cv2.putText(frame, text, (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
	        with self._lock:
            	self._frame = frame

    def get_frame(self):
        """Latest frame as a BGR numpy array, or None if none yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self, quality=80):
        """Latest frame encoded as JPEG bytes, or None."""
        frame = self.get_frame()
        classification = self.classification
        confidence = self.confidence

        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return (buf.tobytes(), classification, confidence) if ok else None

    def release(self):
        self._running = False
        self.cap.release()
