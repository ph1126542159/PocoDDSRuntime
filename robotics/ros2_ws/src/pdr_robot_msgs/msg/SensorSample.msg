uint8 IMU=0
uint8 LIDAR=1
uint8 CAMERA=2
uint8 DEPTH=3
uint8 FORCE_TORQUE=4
uint8 CUSTOM=255

std_msgs/Header header
string name
uint8 type
string encoding
uint32[] shape
float64[] values
uint8[] data
