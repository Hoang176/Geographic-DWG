# -*- coding: utf-8 -*-
"""Geographic.py - Initial UI"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime

class GeographicApp:
    def __init__(self, root):
        self.root=root
        self.root.title('Geographic')
        self.root.geometry('520x260')
        self.root.attributes('-topmost', True)

        frm=ttk.Frame(root,padding=8)
        frm.pack(fill='both',expand=True)

        btns=ttk.Frame(frm)
        btns.pack(fill='x')

        for txt in ['Hệ tọa độ','Xuất KML/KMZ','Nhập KML/KMZ','Lấy từ GG Earth','Lựa chọn']:
            ttk.Button(btns,text=txt).pack(side='left',expand=True,fill='x',padx=2)

        self.log=tk.Text(frm,height=10)
        self.log.pack(fill='both',expand=True,pady=5)

if __name__=='__main__':
    root=tk.Tk()
    GeographicApp(root)
    root.mainloop()
