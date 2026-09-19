from setuptools import find_packages, setup

package_name = 'htn_auto'

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
    description='Autonomous finger control',
    license='MIT',
    entry_points={
        'console_scripts': [
            'auto = htn_auto.auto:main',
        ],
    },
)
