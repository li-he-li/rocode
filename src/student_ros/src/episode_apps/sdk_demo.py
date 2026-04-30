import time
import socket
# import pickle
import json  # 使用 JSON 替换 pickle
import logging
import argparse
import numpy as np
import random

np.set_printoptions(precision=6, suppress=True)
# 设置日志输出格式和级别
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

class EpisodeAPP:
    def __init__(self, ip='localhost', port=12345):
        """
        初始化客户端，设置服务器的IP地址和端口号。
        """
        self.server_address = (ip, port)

    def send_command(self, command):
        """
        发送命令到服务器并接收返回值。

        参数：
            command (dict): 包含动作和参数的命令字典。

        返回：
            从服务器接收到的结果（反序列化后的对象），若发生异常则返回 None。
        """
        try:
            # 使用 with 确保 socket 在使用后能正确关闭
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                # 连接到服务器
                client_socket.connect(self.server_address)

                # 将命令序列化为字节流（使用 JSON）
                data = json.dumps(command).encode('utf-8')
                data_length = len(data)

                # 先发送数据长度（8字节）给服务器，便于服务器知道接收数据的大小
                client_socket.sendall(data_length.to_bytes(8, byteorder='big'))
                # 发送实际的数据
                client_socket.sendall(data)

                # 接收服务器返回的数据长度（8字节）
                response_length = client_socket.recv(8)
                if not response_length:
                    return None
                response_length = int.from_bytes(response_length, byteorder='big')

                # 根据数据长度接收完整的数据包
                response_data = b''
                while len(response_data) < response_length:
                    packet = client_socket.recv(response_length - len(response_data))
                    if not packet:
                        break
                    response_data += packet

                # 将接收到的字节流反序列化为 Python 对象（使用 JSON）
                result = json.loads(response_data.decode('utf-8'))
                return result
        except Exception as e:
            logging.error(f"send_command 出错: {e}")
            return None

    def emergency_stop(self, enable):
        """
        急停或解除急停操作。

        参数：
            enable (int): 1 表示急停，0 表示解除急停。

        返回：
            固定返回 0.05（单位：秒）。
        """
        command = {'action': 'emergency_stop', 'params': enable}
        return self.send_command(command)

    def angle_mode(self, angles, speed_ratio=1):
        """
        通过角度模式控制电机运动，移动到指定关节角度。

        参数：
            angles (list): 各个电机目标角度列表。
            speed_ratio (float): 运动速度比例，默认为 1。

        返回：
            服务器返回的预计运动时间（秒）。
        """
        command = {'action': 'angle_mode', 'params': [angles, speed_ratio]}
        return self.send_command(command)

    def move_xyz_rotation(self, position, orientation, rotation_order="zyx", speed_ratio=1):
        """
        通过 XYZ 坐标和欧拉角控制电机运动，采用普通位姿模式。

        参数：
            position (list): 三维空间位置，包含 [x, y, z]。
            orientation (list): 欧拉角，包含 [roll, pitch, yaw]。
            rotation_order (str): 旋转顺序（支持 "zyx" 或 "xyz"，默认 "zyx"）。
            speed_ratio (float): 运动速度比例（0~1之间，默认 1，超过该范围会自动截断）。

        返回值：
            -1 表示 IK 无解；
            >0 表示有解，返回预计运动时间（秒），建议客户端等待该时间后再发送下一条指令。
        """
        params = position + orientation + [rotation_order, speed_ratio]
        print(params)
        command = {'action': 'move_xyz_rotation', 'params': params}
        return self.send_command(command)

    def move_linear_xyz_rotation(self, position, orientation, rotation_order="zyx"):
        """
        采用直线模式，通过 XYZ 坐标和欧拉角控制电机运动。直线模式下无法调整速度，
        运动过程中服务器会先返回运动时间再执行运动操作（可能会阻塞）。

        参数：
            position (list): 三维空间位置，包含 [x, y, z]。
            orientation (list): 欧拉角，包含 [roll, pitch, yaw]。
            rotation_order (str): 旋转顺序（支持 "zyx" 或 "xyz"，默认 "zyx"）。

        返回值：
            -1 表示 IK 求解无解；
            >0 表示有解，返回预计运动时间（秒）。
        """
        params = position + orientation + [rotation_order]
        command = {'action': 'move_linear_xyz_rotation', 'params': params}
        return self.send_command(command)

    def gripper_on(self):
        """
        启动负压吸盘抓取操作。

        返回：
            固定返回 0.05（单位：秒）。
        """
        command = {'action': 'gripper_on'}
        return self.send_command(command)

    def gripper_off(self):
        """
        负压吸盘释放操作。

        返回：
            固定返回 0.05（单位：秒）。
        """
        command = {'action': 'gripper_off'}
        return self.send_command(command)

    def servo_gripper(self, angle):
        """
        通过舵机控制夹爪角度。

        参数：
            angle (int): 夹爪角度。

        返回：
            固定返回 1（单位：秒）。
        """
        command = {'action': 'servo_gripper', 'params': angle}
        return self.send_command(command)

    def robodk_simu(self, enable):
        """
        控制 Robodk 模拟开关。

        参数：
            enable (int): 1 表示开启模拟，0 表示关闭模拟。

        返回：
            固定返回 0.05（单位：秒）。
        """
        command = {'action': 'robodk_simu', 'params': enable}
        return self.send_command(command)

    def set_free_mode(self, mode):
        """
        设置电机自由模式。注意：在进入自由模式前需要提醒用户准备好托举。

        参数：
            mode (int): 1 进入自由模式，0 退出自由模式。

        返回：
            固定返回 0.1（单位：秒）。
        """
        command = {'action': 'set_free_mode', 'params': mode}
        return self.send_command(command)

    def get_motor_angles(self):
        """
        获取当前电机的角度信息。

        返回：
            一个长度为 6 的角度列表（单位：度）。由于 CAN 总线阻塞，部分电机角度读取可能失败，此时返回 None。
        """
        command = {'action': 'get_motor_angles'}
        return self.send_command(command)

    def get_T(self):
        """
        获取齐次变换矩阵 T。
        """
        command = {'action': 'get_T'}
        result = self.send_command(command)
        if result is None:
            return None
        else:
            # 将列表转换为 numpy 数组并返回
            return np.array(result).reshape(4, 4)
    def get_pose(self,rotation_order="xyz"):
        """
        获取位姿，支持xyz和zyx两种旋转顺序。
        """
        command = {'action': 'get_pose', 'params': rotation_order}
        result = self.send_command(command)
        if result is None:
            return None
        else:
            return np.array(result)

    def dynamic_move(self,goal_pos, current_joint_pulses, motors_max_speed):
        """
        动态移动到目标位置。

        参数：
            goal_pos (list): 目标位置，包含 6 个关节角度。
            current_joint_pulses (list): 当前关节脉冲数，包含 6 个值。
            motors_max_speed (list): 电机最大速度，包含 6 个值。

        返回：
            固定返回 0.05（单位：秒）。
        """
        # goal_pos, current_joint_pulses, motors_max_speed
        command = {'action': 'dynamic_move', 'params': [goal_pos, current_joint_pulses, motors_max_speed]}
        return self.send_command(command)

# 示例使用
if __name__ == '__main__':

    # 创建解析器对象
    parser = argparse.ArgumentParser(description='Episode API Demo')
    # 添加参数
    parser.add_argument('--group_id', type=int, default=1, help='group id (1-4)')
    # 解析命令行参数
    args = parser.parse_args()
    group_id = args.group_id



    # 创建客户端对象
    client = EpisodeAPP(ip='localhost', port=12345)
    # client1 = EpisodeAPP(ip='localhost', port=12346)

    # 先移动到默认位置，等待测试
    # result = client.angle_mode([180.000000, 90.000000, 83.000000, 30.000000, 110.000000, 30.000000], 1)
    # if result < 3:
    #     time.sleep(3)
    # else:
    #     time.sleep(result)

    # ----------------------------以下为测试代码----------------------------

    if group_id == 1:
        # 测试 emergency_stop：急停操作
        result = client.emergency_stop(1)
        print("emergency_stop 急停响应:", result)

        # 测试 emergency_stop：解除急停操作
        result = client.emergency_stop(0)
        print("emergency_stop 解除急停响应:", result)

        # 测试 angle_mode：角度模式控制
        print("即将以 0.2 速度移动到指定关节角度[180.000000, 111.401268, 89.671907, 30.000000, 184.779016, 30.000000]...")
        result = client.angle_mode([180.000000, 111.401268, 89.671907, 30.000000, 184.779016, 30.000000], 0.2)
        print("angle_mode 响应:", result)
        time.sleep(result)

        print("即将以 0.5 速度移动到指定关节角度[180.000000, 145.213396, 90.072883, 30.000000, 27.547795, 30.000000]...")
        result = client.angle_mode([180.000000, 145.213396, 90.072883, 30.000000, 27.547795, 30.000000], 0.8)
        print("angle_mode 响应:", result)
        time.sleep(result)
        print("即将以 1.0 速度移动到指定关节角度[180.000000, 90.000000, 83.000000, 30.000000, 110.000000, 30.000000]...")
        result = client.angle_mode([180.000000, 90.000000, 83.000000, 30.000000, 110.000000, 30.000000], 1)
        print("angle_mode 响应:", result)
        time.sleep(result)

        # 测试 move_xyz_rotation：普通位姿模式控制
        print("即将以 0.5 速度移动到指定位置[357.019928, 0.000000, 305.264329]，朝向[90, 0, 180]，旋转顺序 zyx...")
        result = client.move_xyz_rotation([357.019928,     0.000000,   305.264329], [90,0,180], "zyx", 0.5)
        print("move_xyz_rotation 响应:", result)
        time.sleep(result)
        print("即将以 0.5 速度移动到指定位置[386.940216, 180.254456, 74.679009]，朝向[90, 0, 180]，旋转顺序 zyx...")
        result = client.move_xyz_rotation([386.940216,   180.254456,    74.679009], [90,0,180], "zyx", 0.5)
        print("move_xyz_rotation 响应:", result)
        time.sleep(result)

        # 测试 move_linear_xyz_rotation：直线位姿模式控制
        print("即将直线移动到指定位置[357.019928, 0.000000, 305.264329]，朝向[90, 0, 180]，旋转顺序 zyx...")
        result = client.move_linear_xyz_rotation([357.019928, 0.000000, 305.264329], [90,0,180], "zyx")
        print("move_linear_xyz_rotation 响应:", result)
        time.sleep(result)

    # 测试 group_id = 2
    if group_id == 2:

        # 测试 gripper_on：负压吸盘抓取
        print("即将启动负压吸盘抓取...")
        result = client.gripper_on()
        time.sleep(3)

        # 测试 gripper_off：负压吸盘释放
        print("即将释放负压吸盘...")
        result = client.gripper_off()
        time.sleep(1)

        # 测试 servo_gripper：舵机夹爪控制
        print("即将控制舵机夹爪角度为 45 度...")
        result = client.servo_gripper(45)
        print("servo_gripper 响应:", result)
        time.sleep(2)

        print("即将控制舵机夹爪角度为 90 度...")
        result = client.servo_gripper(900)
        time.sleep(2)

        print("即将控制舵机夹爪角度为 0 度...")
        result = client.servo_gripper(0)
        time.sleep(2)


    if group_id == 3:
         # 测试 set_free_mode：电机自由模式
        print("即将进入自由移动模式，机械臂10秒后进入自由移动模式，注意托举...")
        time.sleep(10)
        result = client.set_free_mode(1)

        t = 0
        while True:
            # 测试 get_motor_angles：获取电机角度
            result = client.get_motor_angles()
            print("get_motor_angles 响应:", result)
            time.sleep(0.5)
            t += 0.5
            if t > 30:
                print("即将退出自由移动模式...")
                result = client.set_free_mode(0)
                break


    if group_id == 4:
        # 测试 robodk_simu：Robodk模拟开关
        print("即将开启 Robodk 同步，机械臂10秒后进入自由移动模式，注意托举...")
        time.sleep(10)
        result = client.robodk_simu(1)

        time.sleep(30)
        print("即将关闭 Robodk 模拟...")
        result = client.robodk_simu(0)

    if group_id == 5:
        # 测试 get_T：获取齐次变换矩阵
        result = client.get_T()
        print(result)

    if group_id == 6:
        # 测试 get_pose：获取位姿，并沿着Z轴旋转
        result = client.get_pose("zyx")
        print(result)
        extra_degree = 10
        while True:
            r = client.move_xyz_rotation([result[0], result[1], result[2]] , [(result[3] + extra_degree), result[4], result[5]], "zyx", 1)
            if r == -1:
                print("IK 无解，退出循环")
                break
            time.sleep(r)
            extra_degree +=10
            if extra_degree > 360:
                break

    if group_id == 7:

        while True:
            # Calculate FPS
            start_time = time.time()

            # Test get_motor_angles: get motor angles
            result = client.get_motor_angles()
            result1 = client1.get_motor_angles()
            # print("get_motor_angles response:", result)
            # print("get_motor_angles response:", result1)

            # Calculate and display FPS
            fps = 1.0 / (time.time() - start_time)
            print(f"FPS: {fps:.2f}, degrees: {result}, degrees1: {result1}")

    if group_id == 8:

        # 测试 dynamic_move：动态移动到目标位置
        # 注意运行该模式，需要：1.驱动板Response改为None，上位机关闭状态刷新

        # 减速比
        gear_ratios = [25, 20, 25, 10, 4, 1]
        # 最大速度
        motors_max_speed = np.array([90, 40, 100, 100, 100, 10]) * 0.5
        # 初始角度 - 这将作为起始点并会累积变化
        angles = [180.00, 90.00, 83.00, 30.00, 110.00, 30.00]
        # 设置目标FPS
        fps = 30

        # 初始化变量用于控制关节角度变化
        direction = 1  # 1表示增加，-1表示减少
        last_direction_change_time = time.perf_counter()

        while True:
            start_time = time.perf_counter()

            # 检查是否需要改变方向（每5秒切换一次）
            if start_time - last_direction_change_time >= 5.0:
                direction *= -1  # 切换方向
                last_direction_change_time = start_time
                # print(f"方向切换: {'增加' if direction == 1 else '减少'}")

            # 在当前角度上累积变化 - 每个关节根据方向变化0.1度
            angles = [angles[i] + direction * 0.3 for i in range(6)]

            # 获取当前电机角度
            current_angle = client.get_motor_angles()
            # 计算当前角度对应的脉冲数
            current_joint_pulses = [int(3200 * gear_ratios[i] * current_angle[i] / 360) for i in range(6)]

            goal_pos = {str(i + 1): float(angles[i]) for i in range(min(6, len(angles)))}

            # 使用controller中的dynamic_move函数来处理关节运动
            client.dynamic_move(
                goal_pos=goal_pos, # 目标角度
                current_joint_pulses=current_joint_pulses, # 当前观测角度脉冲
                motors_max_speed=motors_max_speed.tolist(), # 电机最大速度
            )

            # 等待指定时间，以保持目标FPS
            elapsed_time = time.perf_counter() - start_time
            sleep_time = max(0, 1.0 / fps - elapsed_time)
            time.sleep(sleep_time)

            # 打印FPS
            final_time = time.perf_counter() - start_time
            print(f"FPS: {1.0 / final_time:.2f}, Max fps could be {1.0 / elapsed_time:.2f}")
