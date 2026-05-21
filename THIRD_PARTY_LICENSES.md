# Bundled DLL Licenses

## freenect.dll
- **Source**: [OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect)
- **License**: Apache License 2.0 / GPL-2.0 (dual-licensed)
- **Purpose**: Kinect v1 depth camera driver for Windows

## libusb-1.0.dll
- **Source**: [libusb/libusb](https://github.com/libusb/libusb)
- **License**: LGPL-2.1
- **Purpose**: USB device access library (required by libfreenect)

These DLLs are pre-compiled and bundled for Windows convenience so users
don't need to compile C libraries. On macOS/Linux, install via package
manager instead (`brew install libfreenect` / `apt install freenect`).
