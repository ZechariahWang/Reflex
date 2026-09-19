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
    description='Manual teleop of the exoskeleton hand fingers',
    license='MIT',
    entry_points={
        'console_scripts': [
            'teleop = htn_control.teleop:main',
        ],
    },
)
