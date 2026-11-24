FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

# Install Python tools, serial libraries, and PlatformIO CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-serial \
    python3-yaml \
    python3-pytest \
    ros-jazzy-geometry-msgs \
    ros-jazzy-std-msgs \
    udev \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages platformio

# Automatically source ROS 2 Jazzy in every interactive shell
RUN echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc

WORKDIR /workspace
COPY . /workspace

CMD ["bash", "-c", "source /opt/ros/jazzy/setup.bash && python3 ros2/kai_ros2_bridge.py"]
