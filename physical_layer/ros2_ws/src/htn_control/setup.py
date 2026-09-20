from setuptools import find_packages, setup

package_name = 'htn_control'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='zech',
    maintainer_email='zechariahwang@gmail.com',
    description='Hand HAL (sim / feetech backends) and keyboard teleop',
    license='MIT',
    entry_points={
        'console_scripts': [
            'teleop = htn_control.teleop:main',
            'hal = htn_control.hal_node:main',
            'teleop_gui = htn_control.teleop_gui:main',
            'servo_tool = htn_control.servo_tool:main',
            'linkage_publisher = htn_control.linkage_publisher:main',
            'iphone_camera_node = htn_control.iphone_camera_node:main',
        ],
    },
)
