'''
@File: jdCake.py
@Author: ritter
@Version: 2.0
@Description:
'''
import time
from io import BytesIO
import re
import json
import os
from pprint import pprint
import platform

import requests
from PIL import Image
from pyzbar import pyzbar

def qrcode_decode(image):
    zbar = pyzbar.decode(image)
    data = None
    for zb in zbar:
        data = zb.data.decode("utf-8")
    return data

def getQRCode(session):
    url = "https://qr.m.jd.com/show"
    params = {
        "appid": "133",
        "size": "147",
        "t": str(int(time.time() * 1000))
    }
    resp = session.get(url, params=params)
    return resp.content

def showQRCode(raw):
    image = Image.open(BytesIO(raw))
    if platform.system() == "Windows":
        image.show()
    else:
        url = qrcode_decode(image)
        cmd = "qrencode -o - -t utf8 {}".format(url)
        os.system(cmd)

def checkQRCode(session):
    url = "https://qr.m.jd.com/check"
    params = {
        "callback": "jQuery6419664",
        "appid": "133",
        "token": session.cookies["wlfstk_smdl"],
        "_": str(int(time.time() * 1000))
    }
    resp = session.get(url, params=params)
    return json.loads(re.findall("jQuery6419664\((.*)\)", resp.text, re.S)[0])

def qrCodeTicketValidation(session, ticket):
    url = "https://passport.jd.com/uc/qrCodeTicketValidation"
    params = {
        "t": ticket
    }
    resp = session.get(url, params=params)
    return resp.json()

def saveCookies(session):
    cookies = session.cookies.get_dict()
    with open("cookies.json", "w") as f:
        json.dump(cookies, f, indent=4)

def getUserInfo(session):
    url = "https://passport.jd.com/user/petName/getUserInfoForMiniJd.action"
    params = {
        "callback": "jQuery6419664",
        "_": str(int(time.time() * 1000))
    }
    resp = session.get(url, params=params)
    respd = re.findall("jQuery6419664\((.*)\)", resp.text, re.S)[0]
    if respd == "null({})":
        # cookie过期
        return {}
    return json.loads(respd)

def login(session):
    raw = getQRCode(session)
    showQRCode(raw)
    ticket = None
    while 1:
        msg = checkQRCode(session)
        time.sleep(2)
        print(msg)
        if msg["code"] == 201 or msg["code"] == 202:
            continue
        if msg["code"] == 203 or msg["code"] == 205:
            return
        if msg["code"] != 200:
            return
        ticket = msg["ticket"]
        break
    resp = qrCodeTicketValidation(session, ticket)
    if resp["returnCode"] != 0:
        print(resp)
        return
    saveCookies(session)

def getHomeDataSecretp(session):
    action_url = "https://api.m.jd.com/client.action"
    body = {
        "functionId": "cakebaker_getHomeData",
        "body": {},
        "client": "wh5",
        "clientVersion": "1.0.0"
    }
    resp = session.post(action_url, data=body).json()
    # 获取签名
    secretp = resp["data"]["result"]["cakeBakerInfo"]["secretp"]
    return secretp

def getTaskDetail(session):
    action_url = "https://api.m.jd.com/client.action"
    body = {
        "functionId": "cakebaker_getTaskDetail",
        "body": {},
        "client": "wh5",
        "clientVersion": "1.0.0"
    }
    resp = session.post(action_url, data=body)
    return resp.json()

def getFeedDetail(session, task_ids):
    action_url = "https://api.m.jd.com/client.action"
    body = {
        "functionId": "cakebaker_getFeedDetail",
        "body": '{"taskIds":"%s"}' % task_ids,
        "client": "wh5",
        "clientVersion": "1.0.0"
    }
    resp = session.post(action_url, data=body)
    return resp.json()

def superiorTask(session, task_ids):
    resp = getFeedDetail(session, task_ids)
    # 确认任务集合所在键名
    result = resp["data"]["result"]
    task_keys = list(filter(lambda key: key.endswith("Vos") and key != "taskVos", result.keys()))
    if len(task_keys) == 0:
        return []
    task_key = task_keys[0]
    todo_tasks = []
    for superior_task in result[task_key]:
        # 1 未完成 2 已完成
        status = superior_task["status"]
        if status == 2:
            continue
        # 剩余次数
        count = superior_task["maxTimes"] - superior_task["times"]
        if count == 0:
            continue
        # 加购商品id
        goods_id = [goods["itemId"] for goods in superior_task["productInfoVos"] if goods["status"] == 1]
        for _ in range(count):
            t = {
                "taskName": superior_task["taskName"],
                "taskId": superior_task["taskId"],
                "taskType": superior_task["taskType"],
                "waitDuration": superior_task["waitDuration"],
                "itemId": goods_id.pop()
            }
            todo_tasks.append(t)
    return todo_tasks

def genTaskQueue(session, tasks):
    # 跳过部分邀请任务
    func = lambda task: task["taskName"].find("邀请") == -1 and task["taskName"].find("邀人") == -1 and \
                        task["taskName"].find("战队") == -1
    tasks = filter(func, tasks)
    all_todo_tasks = []
    for task in tasks:
        # 1 未完成 2 已完成
        if task["status"] == 2:
            continue

        # 加购类任务
        if task.get("productInfoVos"):
            task_ids = ",".join([item["itemId"] for item in task["productInfoVos"]])
            todo_tasks = superiorTask(session, task_ids)
            all_todo_tasks.extend(todo_tasks)
            continue

        count = task["maxTimes"] - task["times"]
        task_key = None
        # 小精灵、签到、趣味游戏等任务
        if task.get("simpleRecordInfoVo"):
            task_key = "simpleRecordInfoVo"
        # 浏览任务
        elif task.get("shoppingActivityVos"):
            task_key = "shoppingActivityVos"
        # 逛店铺任务
        elif task.get("browseShopVo"):
            task_key = "browseShopVo"
        else:
            print("任务名称[{taskName}]类型未知, task => {task}".format(task["taskName"], task=task))
            continue

        items = task[task_key]
        item_ids = None
        if isinstance(items, dict):
            item_ids = [items["itemId"] for _ in range(count)]
        elif isinstance(items, list):
            item_ids = [item["itemId"] for item in items if item["status"] == 1]
        else:
            print("任务名称[{taskName}]子项类型未知, task => {task}".format(task["taskName"], task=task))
            continue

        for _ in range(count):
            t = {
                "taskName": task["taskName"],
                "taskId": task["taskId"],
                "taskType": task["taskType"],
                "waitDuration": task["waitDuration"],
                "itemId": item_ids.pop()
            }
            all_todo_tasks.append(t)

    return all_todo_tasks

def doTask(session, secretp, task_queue):
    while len(task_queue) > 0:
        task = task_queue.pop(0)
        action_url = "https://api.m.jd.com/client.action"
        body = {
            "functionId": "cakebaker_ckCollectScore",
            "body": json.dumps({
                "taskId": task["taskId"],
                "itemId": task["itemId"],
                "actionType": 1,
                "safeStr": {"secretp": secretp}
            }),
            "client": "wh5",
            "clientVersion": "1.0.0"
        }
        # 除了 小精灵 0 连签 13 加购 2 去领新人专享福利 3 去玩AR吃蛋糕小游戏 20 的任务都要执行2次
        if task["taskType"] not in [0, 13, 2, 3, 20]:
            resp = session.post(action_url, data=body).json()
            if resp["data"]["success"]:
                print("任务[{taskName}]领取成功👌".format(taskName=task["taskName"]))
                time.sleep(2 + task["waitDuration"])
            else:
                print("任务[{taskName}]领取失败😱, 失败原因[{message}]".format(
                    taskName=task["taskName"],
                    message=resp["data"].get("bizMsg", "")
                ))
                continue

        inner_body = json.loads(body["body"])
        del inner_body["actionType"]
        body["body"] = json.dumps(inner_body)
        resp = session.post(action_url, data=body).json()
        if resp["data"]["success"]:
            print("任务[{taskName}]执行成功👌，获得金币💰{score}, 当前任务剩余次数👉{times}".format(
                taskName=task["taskName"],
                score=resp["data"]["result"].get("score", 0),
                times=resp["data"]["result"].get("maxTimes", 0) - resp["data"]["result"].get("times", 0)
            ))
        else:
            print("任务[{taskName}]执行失败😱, 失败原因[{message}]".format(
                    taskName=task["taskName"],
                    message=resp["data"].get("bizMsg", "")
                ))

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "jdapp",
        "referer": "https://passport.jd.com/new/login.aspx?ReturnUrl=http%3A%2F%2Fhome.jd.com%2F"
    })
    if os.path.exists("cookies.json"):
        cookies = None
        with open("cookies.json") as f:
            cookies = json.load(f)
        session.cookies.update(cookies)
    else:
        login(session)
    # 测试登录状态是否有效
    resp = getUserInfo(session)
    if resp.get("nickName"):
        print("🎈欢迎你, {nickName}".format(nickName=resp["nickName"]))
    else:
        print("登录状态已过期😱, 请重新扫码登录")
        session.cookies.clear()
        login(session)
    session.headers.update({
        "origin": "https://home.m.jd.com",
        "referer": "https://home.m.jd.com/myJd/newhome.action"
    })
    secretp = getHomeDataSecretp(session)
    i = 0
    while 1:
        i += 1
        print("第{}次抓取🕷️".format(i))
        resp = getTaskDetail(session)
        if resp["data"]["bizCode"] != 0:
            print(f"错误{resp['msg']}")
            return
        tasks = resp["data"]["result"]["taskVos"]
        all_todo_tasks = genTaskQueue(session, tasks)
        print("📃任务列表：")
        pprint(all_todo_tasks, indent=2)
        print("📃抓取任务总数：%d" % len(all_todo_tasks))
        if len(all_todo_tasks) == 0:
            print("任务都已经做完啦~🤪")
            break
        time.sleep(3)
        print("开始执行➡")
        doTask(session, secretp, all_todo_tasks)
        print("📃任务完成")
        print("Again ...")

if __name__ == '__main__':
    main()