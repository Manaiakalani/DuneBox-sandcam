# Bundled DLL Licenses

## freenect.dll
- **Source**: [OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect)
- **License**: Apache License 2.0 / GPL-2.0 (dual-licensed)
- **Purpose**: Kinect v1 depth camera driver for Windows

## libusb-1.0.dll
- **Source**: [libusb/libusb](https://github.com/libusb/libusb)
- **License**: LGPL-2.1
- **Purpose**: USB device access library (required by libfreenect)

These two DLLs are the Windows Kinect v1 driver, bundled so a v1 camera works without compiling libfreenect. The Windows install defaults to Kinect v2, which uses Kinect20.dll from the Kinect for Windows Runtime rather than these files. The upstream links above are the license texts for the LGPL and the Apache-2.0 / GPL-2.0 dual license.
