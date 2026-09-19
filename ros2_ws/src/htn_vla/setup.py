from setuptools import find_packages, setup

package_name = 'htn_vla'

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
    description='Autonomous finger control from the VLA policy',
    license='MIT',
    entry_points={
        'console_scripts': [
            'vla = htn_vla.vla:main',
        ],
    },
)
