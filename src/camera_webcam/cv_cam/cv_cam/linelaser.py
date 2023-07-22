#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, Image
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
import cv2
import numpy as np
import time
import math

class PIDController:
    def __init__(self, kp, ki, kd, setpoint):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.error = 0.0
        self.last_error = 0.0
        self.error_sum = 0.0
        self.last_time = time.time()

    def update(self, current_value):
        current_time = time.time()
        dt = current_time - self.last_time

        self.error = self.setpoint - current_value
        self.error_sum += self.error * dt
        error_diff = (self.error - self.last_error) / dt

        output = self.kp * self.error + self.ki * self.error_sum + self.kd * error_diff

        self.last_error = self.error
        self.last_time = current_time

        return output

class CombinedDetectionNode(Node):
    def __init__(self):
        super().__init__('combined_detection_node')

        # Set the desired obstacle detection range
        self.min_angle = -30.0  # Minimum angle (degrees)
        self.max_angle = 30.0   # Maximum angle (degrees)

        # Subscribe to the LaserScan topic
        self.laser_subscription = self.create_subscription(
            LaserScan,
            '/scan',
            self.obstacle_detection_callback,
            10  # Adjust the queue size as needed
        )

        # Subscribe to the camera image topic
        self.camera_subscription = self.create_subscription(
            Image,
            'camera/image_raw',
            self.line_detection_callback,
            10
        )

        self.image_pub = self.create_publisher(Image, "camera/cv_image", 10)

        # Publish Twist commands to control the robot
        self.publisher = self.create_publisher(Twist, 'cmd_vel', 10)

        # Initialize the Twist message to move forward
        self.twist_cmd = Twist()
        self.twist_cmd.linear.x = 0.5  # Set the linear speed (adjust as needed)

        # Variable to track the last time an obstacle was detected
        self.last_obstacle_time = time.time()
        
        self.obstacle_detected = False
        
        self.stop_time = 0.0
        self.last_line_detection_time = time.time()        

        # Line detection variables
        self.RLine = 0
        self.point_count = 0
        self.last_point_count = 0
        self.count = 0
        self.middle = 0
        self.mark = 0
        self.count_mark = 0
        # Flag to indicate if retreat is in progress
        self.retreat_in_progress = False        

        self.start_time = time.time()

        self.pid_controller = PIDController(kp=5.0, ki=0.0, kd=0.0, setpoint=80)
        self.max_linear_speed = 0.5
        self.max_angular_speed = 0.1
        self.angular_speed = 0.0
        self.linear_speed = 0.0
        self.linear_speed_reduction_factor = 1.0  # Adjust the reduction factor as needed
        self.previous_angular_speed = 0.0

    def obstacle_detection_callback(self, msg):
        # Convert LaserScan angles to radians
        angles = np.arange(msg.angle_min, msg.angle_max, msg.angle_increment)

        # Filter the laser scan data within the desired range
        filtered_ranges = []
        for angle, distance in zip(angles, msg.ranges):
            if self.min_angle <= np.degrees(angle) <= self.max_angle:
                filtered_ranges.append(distance)

        # Check for obstacles within the desired range
        self.obstacle_detected = any(distance < 0.65 for distance in filtered_ranges)  # Adjust the threshold as needed

        if self.obstacle_detected:
            self.stop_time = time.time()
            self.obstacle_detected = True
            self.publish_velocity(0.0, 0.0)
        else:
            # If no obstacle is detected, check the time difference before allowing the robot to move forward again
            if self.obstacle_detected and time.time() - self.stop_time >= 2.0:
                self.obstacle_detected = False

    def line_detection_callback(self, msg):
        # Check if there is a delay needed after obstacle detection
        if self.obstacle_detected and time.time() - self.stop_time < 2.0:
            # Delay the line detection callback for 2 seconds after stopping
            time.sleep(2.0 - (time.time() - self.stop_time))
            return       
        
        # Convert the ROS2 Image message to OpenCV format
        bridge = CvBridge()
        frame = bridge.imgmsg_to_cv2(msg, "bgr8")

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kernel_size = 5
        blur_gray = cv2.GaussianBlur(gray_frame, (kernel_size, kernel_size), 0)
        ret, thresh = cv2.threshold(gray_frame, 80, 255, cv2.THRESH_BINARY)

        diff = []
        points = []
        start_height = []
        self.middle = 0

        # Calculate the number of rows based on image height
        num_rows = min(5, frame.shape[0] // 15)

        for i in range(num_rows):
                start_height.append(thresh.shape[0] - 1 - (15 * i))
                signed_thresh = thresh[start_height[i]].astype(np.int16)
                diff.append(np.diff(signed_thresh))

                points.append(np.where(np.logical_or(diff[i] > 200, diff[i] < -200)))
                cv2.line(frame, (0, start_height[i]), (thresh.shape[1], start_height[i]), (255, 0, 0), 2)

                self.point_count = 0
                for j in range(len(points[i][0])):
                    self.middle = points[i][0][j]
                    cv2.circle(frame, (self.middle, start_height[i]), 5, (0, 0, 255), 2)
                    cv2.circle(frame, (thresh.shape[1] // 2, start_height[i]), 5, (255, 0, 0), 2)
                    cv2.line(frame, (self.middle, start_height[i]), (thresh.shape[1] // 2, start_height[i]), (0, 255, 0), 2)
                    
                    
                    if i == 4:
                        self.point_count += 1
                    
                    
                if self.point_count != self.last_point_count:
                    self.last_point_count = self.point_count
                    # print("point_count:", self.point_count)

                    if self.point_count >= 10:
                        if self.mark == 0:
                            self.count_mark +=1                            
                            self.count += 1
                            self.mark = 1
                            print("Count:", self.count)
                            print("RLine:", self.RLine)
                            print("Mark:", self.mark)
                            print("Count_Mark:", self.count_mark)

                    
                    if self.point_count == 2:
                        self.mark = 0
                        if self.count >= 2:

                            if self.RLine == 1:
                                self.RLine = 0
                                
                            else:
                                self.RLine = 1
                            self.count = 0
                            print("Count:", self.count)
                            print("RLine:", self.RLine)
                            print("Mark:", self.mark)


                if len(points) >= 5:
                    if self.RLine == 1:
                        if len(points[4][0]) > 0:
                            rr = len(points[4][0])
                            self.middle = points[4][0][rr-1] 
                            #print("R5",self.middle)
                    else :
                        if len(points[4][0]) > 0:
                            self.middle = points[4][0][0]
                            #print("L5",self.middle)
                            
                    if self.middle == 0:
                        if self.RLine == 1:
                            if len(points[3][0]) > 0:
                                rr = len(points[3][0])
                                self.middle = points[3][0][rr-1] 
                                #print("R5",self.middle)
                        else :
                            if len(points[3][0]) > 0:
                                self.middle = points[3][0][0]
                                #print("L5",self.middle)
                    if self.middle == 0:
                        if self.RLine == 1:
                            if len(points[2][0]) > 0:
                                rr = len(points[2][0])
                                self.middle = points[2][0][rr-1] 
                                #print("R5",self.middle)
                        else :
                            if len(points[2][0]) > 0:
                                self.middle = points[2][0][0]
                                #print("L5",self.middle)
                    if self.middle == 0:
                        if self.RLine == 1:
                            if len(points[1][0]) > 0:
                                rr = len(points[1][0])
                                self.middle = points[1][0][rr-1] 
                                #print("R5",self.middle)
                        else :
                            if len(points[1][0]) > 0:
                                self.middle = points[1][0][0]
                                #print("L5",self.middle)
        
        if self.obstacle_detected:
            # If an obstacle is detected while on the line, stop the robot
            self.angular_speed = 0.0
            self.linear_speed = 0.0

        else:
            # Line following behavior
            if self.middle != 0:
                self.angular_speed = self.calculate_angular_speed(self.middle)
                self.linear_speed = self.calculate_linear_speed(self.angular_speed)                
            else:
                # If the line is lost, stop the robot
                self.angular_speed = self.calculate_angular_speed(self.middle)
                self.linear_speed = self.calculate_linear_speed(self.angular_speed)
                self.get_logger().info("Not found!!!")

            self.twist_cmd.angular.z = self.angular_speed
            self.twist_cmd.linear.x = self.calculate_linear_speed(self.twist_cmd.angular.z)

            # Publish the velocity commands
            self.publish_velocity(self.linear_speed, self.angular_speed)

        img_msg = bridge.cv2_to_imgmsg(frame, "bgr8")
        self.image_pub.publish(img_msg)         
        # Check if count_mark reaches 5
        if self.count_mark == 5:
            self.angular_speed = 0.0
            self.linear_speed = 0.0
            self.count_mark = 0
            self.publish_velocity(self.linear_speed, self.angular_speed)

        # Check if count_mark reaches 5
        if self.count_mark == 5:
            self.angular_speed = 0.0
            self.linear_speed = 0.0
            self.count_mark = 0
            self.publish_velocity(self.linear_speed, self.angular_speed)                 

    def calculate_linear_speed(self, angular_speed):
        if self.previous_angular_speed != 0.0 and angular_speed != self.previous_angular_speed:
            linear = self.max_linear_speed * self.linear_speed_reduction_factor
        else:
            linear = self.max_linear_speed

        if linear > self.max_linear_speed:
            linear = self.max_linear_speed

        self.previous_angular_speed = angular_speed
        return linear

    def calculate_angular_speed(self, pp):
        err = (pp - 80)*(-1)
        val = err / 800
        return val
        
    def publish_velocity(self, linear, angular):
        twist_msg = Twist()
        twist_msg.linear.x = linear
        twist_msg.angular.z = angular
        self.publisher.publish(twist_msg)      

def main(args=None):
    rclpy.init(args=args)
    combined_detection_node = CombinedDetectionNode()
    rclpy.spin(combined_detection_node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
