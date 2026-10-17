from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
image=Image.new("RGBA",(256,256),(0,0,0,0));draw=ImageDraw.Draw(image)
draw.rounded_rectangle((8,8,248,248),radius=52,fill="#137b80")
for i,color in enumerate(["#55c6ac","#93d59b","#efcf64","#f69b5a"]):
    x=54+i*39;draw.rounded_rectangle((x,60,x+23,195),radius=7,fill=color)
draw.line((36,130,220,130),fill="#f8fffe",width=5)
draw.ellipse((111,115,145,149),outline="white",width=5)
folder=ROOT/"src"/"mutex_imatest"/"assets";folder.mkdir(exist_ok=True)
image.save(folder/"app.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(folder/"app-icon.png")

