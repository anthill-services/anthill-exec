
from setuptools import setup, find_packages

DEPENDENCIES = [
    "anthill-common",
    "v8py==0.9.14"
]

setup(
    name='anthill-exec',
    package_data={
      "anthill.exec": ["anthill/exec/sql", "anthill/exec/static"]
    },
    setup_requires=["pypigit-version"],
    git_version="0.1.0",
    description='Server-side javascript code execution for Anthill platform',
    author='desertkun',
    license='MIT',
    author_email='desertkun@gmail.com',
    url='https://github.com/anthill-platform/anthill-exec',
    namespace_packages=["anthill"],
    include_package_data=True,
    packages=find_packages(),
    dependency_links=[
        'https://cdn.anthillplatform.org/python/v8py'
    ],
    zip_safe=False,
    install_requires=DEPENDENCIES
)
