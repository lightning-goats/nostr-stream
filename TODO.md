# Future work

- Automate the YouTube live thumbnail from an OBS program-frame capture. When
  a new local stream is detected, capture one composed frame, identify the
  active YouTube broadcast, and upload the image with YouTube Data API
  `thumbnails.set`. This needs one-time YouTube OAuth authorization and should
  run once per broadcast.
