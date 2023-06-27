import asyncio
from pytec.aioclient import Client

async def main():
    tec = Client()
    await tec.connect() #(host="192.168.1.26", port=23)
    await tec.set_param("s-h", 1, "t0", 20)
    print(await tec.get_pwm())
    print(await tec.get_pid())
    print(await tec.get_pwm())
    print(await tec.get_postfilter())
    print(await tec.get_steinhart_hart())
    async for data in tec.report_mode():
        print(data)

asyncio.run(main())
