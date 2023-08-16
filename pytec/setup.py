from setuptools import setup, find_packages

setup(
    name="pytec",
    version="0.0",
    author="M-Labs",
    url="https://git.m-labs.hk/M-Labs/thermostat",
    description="Control TEC",
    license="GPLv3",
    install_requires=["setuptools"],
    packages=find_packages(),
    entry_points={
        "gui_scripts": [
            "tec_qt = tec_qt:main",
        ]
    },
    py_modules=['tec_qt', 'ui_tec_qt', 'autotune', 'waitingspinnerwidget'],
)
