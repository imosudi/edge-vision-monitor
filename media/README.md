# Prerecorded Video Media Directory

Place prerecorded video files (`.mp4`, `.avi`, `.mkv`, `.mov`) in this directory for playback through the Edge Vision Monitor platform.

---

## 1. Directory Structure

```text
media/
├── sample.mp4          # Example traffic or test footage
├── benchmark.mp4
└── README.md
```

---

## 2. Supported Formats & Codecs

- Formats: MP4, AVI, MKV, MOV
- Video Codecs: H.264, MPEG-4, MJPEG
- Recommended Resolution: 640x480 or 1280x720 for edge inference efficiency

---

## 3. Playback Features

- **Pacing**: Playback rate matches the video's native frame rate rather than running at uncontrolled speeds.
- **Looping**: Configurable via `video.loop_playback` in configuration.
- **Controls**: Interactive Play, Pause, and Restart controls available in the dashboard and REST API.
- **Fallback**: If no video file is present, the platform automatically generates a procedural synthetic edge stream for continuous monitoring tests.
