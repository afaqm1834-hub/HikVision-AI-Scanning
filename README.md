# Real-Time Employee Attendance

Headless Python service for multi-camera employee attendance using Hikvision RTSP streams, SCRFD face detection, ArcFace embeddings, ONNX Runtime inference, and a Node.js attendance API.

## Features

- Separate process per RTSP camera for stability
- Multi-face detection and recognition in the same frame
- SCRFD ONNX face detection with 5-point landmarks
- ArcFace ONNX embeddings with multiple stored embeddings per employee
- Multi-frame confirmation to reduce false positives
- Cooldown-based duplicate suppression
- API retry logic with `x-api-key`
- Unknown face image capture
- Daily rotating log files
- RTSP auto-reconnect and worker auto-restart

## Project Layout

```text
app/
  main.py
  camera_worker.py
  recognition.py
  api_client.py
  config.yaml
  employees.json
  utils/
    config.py
    enroll_embeddings.py
    logging_utils.py
```

## Install

```bash
pip install -r requirements.txt
```

Runtime dependencies:

- `opencv-python`
- `onnxruntime`
- `numpy`

## Configure

1. Edit [app/config.yaml](/d:/HikVision%20AI%20Tracking/app/config.yaml) with real RTSP URLs, API base URL, API key, and ONNX model paths.
2. Keep `threshold` conservative at first, usually `0.55` to `0.60`.
3. Use at least 3 to 5 clear images per employee for enrollment.
4. Place the models here by default:
   `app/models/scrfd_500m_bnkps.onnx`
   `app/models/w600k_r50.onnx`

`config.yaml` is stored as JSON syntax so it can be parsed with Python standard library only.

## Build Employee Embeddings

Create a folder like:

```text
dataset/
  1_Ali/
    img1.jpg
    img2.jpg
    img3.jpg
  2_Sara/
    img1.jpg
    img2.jpg
    img3.jpg
```

Run:

```bash
python app/utils/enroll_embeddings.py --input-dir dataset
```

This writes [app/employees.json](/d:/HikVision%20AI%20Tracking/app/employees.json).

## Run

Preferred:

```bash
python -m app.main
```

Direct script execution is also supported:

```bash
python app/main.py
```

## Operational Notes

- Unknown faces are saved under `logs/unknown_faces`.
- Each camera process reconnects after stream failure.
- The parent process restarts dead camera workers automatically.
- Duplicate attendance events are suppressed for `cooldown_seconds`.
- Consecutive-frame confirmation uses a lightweight IoU track association, not a full tracker.
- The SCRFD model must include landmark outputs (`bnkps`) because ArcFace alignment depends on 5 facial keypoints.

## Deployment Notes

- Use stable employee photos with frontal faces and consistent lighting.
- If false positives appear, increase `threshold`, `min_frames`, or both.
- If misses increase, lower `process_every_n_frames` or use higher-resolution streams.
- For CPU-only systems, start with 720p streams and process every 3rd frame.
