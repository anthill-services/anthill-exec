
from setuptools import setup

DEPENDENCIES = [
    "anthill-common",
    "v8py==0.9.14"
]

setup(
    name='anthill-exec',
    setup_requires=["pypigit-version"],
    git_version="0.1.0",
    description='Server-side javascript code execution for Anthill platform',
    author='desertkun',
    license='MIT',
    author_email='desertkun@gmail.com',
    url='https://github.com/anthill-platform/anthill-exec',
    namespace_packages=["anthill"],
    packages=["anthill.exec"],
    zip_safe=False,
    install_requires=DEPENDENCIES
)
