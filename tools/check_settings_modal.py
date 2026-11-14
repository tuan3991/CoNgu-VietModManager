# -*- coding: utf-8 -*-
"""Kiểm tra nhanh tính toàn vẹn cấu trúc HTML của Menu Cài Đặt Trung Tâm."""
import re

PATH = "static/index.html"
html = open(PATH, encoding="utf-8").read()

marker = 'id="settingsModal"'
start = html.rindex("<div", 0, html.index(marker))
end = html.index("TOAST NOTIFICATION CONTAINER", start)
block = html[start:end]

opens = len(re.findall(r"<div\b", block))
closes = len(re.findall(r"</div>", block))
print(f"settingsModal block -> <div>: {opens}  </div>: {closes}  balanced: {opens == closes}")

doc_open = len(re.findall(r"<div\b", html))
doc_close = len(re.findall(r"</div>", html))
print(f"whole document      -> <div>: {doc_open}  </div>: {doc_close}  balanced: {doc_open == doc_close}")

panels = re.findall(r'id="settingsPanel-([a-z_]+)"', html)
tabs = re.findall(r'id="settingsTabBtn-([a-z_]+)"', html)
print("panels:", panels)
print("tabs  :", tabs)
print("matching tab/panel sets:", sorted(panels) == sorted(tabs))