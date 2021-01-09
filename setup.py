
from setuptools import setup, find_namespace_packages

DEPENDENCIES = [
    "anthill-common>=0.2.5",
    "v8py==0.9.14"
]

setup(
    name='anthill-exec',
    package_data={
      "anthill.exec": ["anthill/exec/sql", "anthill/exec/static"]
    },
    version='0.2',
    description='Server-side javascript code execution for Anthill platform',
    author='desertkun',
    license='MIT',
    author_email='desertkun@gmail.com',
    url='https://github.com/anthill-platform/anthill-exec',
    namespace_packages=["anthill"],
    include_package_data=True,
    packages=find_namespace_packages(include=["anthill.*"]),
    dependency_links=[
        'https://cdn.anthillplatform.org/python/v8py'
    ],
    zip_safe=False,
    install_requires=DEPENDENCIES
)
