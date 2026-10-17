"""Password-encrypted, raster-only portable chart definitions (``.mxtpl``).

The ZIP is a transport container, not the encryption boundary. AES-256-GCM
authenticates the complete MsgPack payload and the public format manifest; a
fresh salt/nonce is generated for every export and Scrypt derives the key from
the user's password. There is no embedded application key or password recovery.

Only measurement geometry and raster registration references are transported;
SVG/PDF artwork is never copied into a package. After successful import, the
reference PNGs are ordinary local working-cache files. This protects the
distribution package and original vectors, not screenshots or an authorized
recipient's access to the raster/measurement definition.

API references: https://cryptography.io/en/latest/hazmat/primitives/aead/
https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import zipfile
import zlib

import msgpack
from PIL import Image
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .models import ChartDefinition, REGION_KINDS

PACKAGE_SUFFIX = ".mxtpl"
PACKAGE_FORMAT = "MUTEX Encrypted Chart Package"
PACKAGE_VERSION = 1
REFERENCE_MAX_SIDE = 4096
THUMBNAIL_MAX_SIDE = 512
MAX_PAYLOAD_BYTES = 64 * 2**20 - 16
MAX_CIPHERTEXT_BYTES = MAX_PAYLOAD_BYTES + 16
MAX_PACKAGE_BYTES = MAX_CIPHERTEXT_BYTES + 65536
MAX_IMAGE_BYTES = 32 * 2**20
MAX_DEFINITION_BYTES = 16 * 2**20
MAX_MANIFEST_BYTES = 4096
MAX_REGIONS = 20000
MAX_FIDUCIALS = 50000
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 32768, 8, 1
_PNG = b"\x89PNG\r\n\x1a\n"
_ENTRIES = {"manifest.json", "encrypted.bin"}
_CHART_FIELDS = {"id", "name", "regions", "physical_size_mm", "reference_size",
    "calibrated", "fiducials", "preview", "source_path", "source_page",
    "asset_license", "schema_version", "notes", "aliases"}
_REGION_FIELDS = {"id", "kind", "box", "label", "params", "enabled"}
_PRIVATE_KEY = re.compile(r"(?:^|_)(?:path|paths|filename|filepath|file_path|source_bytes|source_text|source_data|svg|pdf|vector|artwork|href)(?:$|_)", re.I)
_ABSOLUTE_PATH = re.compile(r"(?i)(?<![A-Z0-9])(?:file:/+|[a-z]:[\\/]|\\\\)[^\r\n\"<>|]*")
_UNIX_PATH = re.compile(r"(?<![\w:/])/(?:[^\s/\\:\"<>|]+/)+[^\r\n\"<>|，。;；,]*")
_VECTOR_TEXT = re.compile(r"<\s*(?:svg|path|polygon|polyline|rect|g|defs)\b|<\?xml\b|%PDF-", re.I)


class ChartPackageError(ValueError):
    """Malformed, unsupported, oversized, or unusable template package."""


class ChartPackagePasswordError(ChartPackageError):
    """Password is invalid, or authentication failed (wrong key/tampered data)."""


def _password_bytes(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        raise ChartPackagePasswordError("模板口令需为 8–1024 个字符；请妥善保存，软件不能找回口令")
    encoded = password.encode("utf-8")
    if len(encoded) > 4096:
        raise ChartPackagePasswordError("模板口令过长")
    return encoded


def _derive(password, salt):
    # Fixed, validated work factors prevent an untrusted manifest requesting
    # arbitrary CPU/memory allocations before its authentication is checked.
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(password)


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("ascii")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ChartPackageError("模板数据包含重复或非文本字段")
        result[key] = value
    return result


def _scrub(value, *, depth=0, budget=None):
    """Copy JSON-like metrology data; discard filesystem/artwork attachments."""
    if budget is None:
        budget = [1_000_000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 20:
        raise ChartPackageError("模板定义层级或元素过多")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > 2**53:
            raise ChartPackageError("模板数字超出支持范围")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ChartPackageError("模板包含非有限数值")
        return value
    if isinstance(value, str):
        if len(value) > 65536:
            raise ChartPackageError("模板文字过长")
        if _VECTOR_TEXT.search(value):
            raise ChartPackageError("模板参数中不能嵌入 SVG/PDF 或矢量源码")
        return _UNIX_PATH.sub("[local path removed]", _ABSOLUTE_PATH.sub("[local path removed]", value))
    if isinstance(value, (list, tuple)):
        if len(value) > 200000:
            raise ChartPackageError("模板数组过长")
        return [_scrub(v, depth=depth+1, budget=budget) for v in value]
    if isinstance(value, dict):
        if len(value) > 100000 or any(not isinstance(k, str) or len(k)>256 for k in value):
            raise ChartPackageError("模板字段无效")
        return {k: _scrub(v, depth=depth+1, budget=budget)
            for k,v in value.items() if not _PRIVATE_KEY.search(k)}
    raise ChartPackageError("模板参数仅支持 JSON 类型；不支持二进制或可执行对象")


def _definition(chart):
    if not isinstance(chart, ChartDefinition):
        raise ChartPackageError("需要有效的图卡定义")
    data = copy.deepcopy(chart.to_dict())
    # Remove local references before recursive scrubbing. Every other value,
    # including calibration, fiducials, aliases and license, is preserved.
    data["source_path"] = None
    data["preview"] = None
    data["source_page"] = 0
    data = _scrub(data)
    data["source_path"] = None
    data["preview"] = None
    _validate_definition(data)
    if len(msgpack.packb(data, use_bin_type=True)) > MAX_DEFINITION_BYTES:
        raise ChartPackageError("模板定义超过 16 MiB")
    return data


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_definition(data):
    if not isinstance(data, dict) or set(data) != _CHART_FIELDS:
        raise ChartPackageError("模板定义字段不完整或不受支持")
    if any(not isinstance(data[k],str) or not data[k] or len(data[k])>512 for k in ("id","name")):
        raise ChartPackageError("模板名称或标识无效")
    for key, limit in (("notes",65536), ("asset_license",65536)):
        if not isinstance(data[key], str) or len(data[key]) > limit:
            raise ChartPackageError("模板说明或许可无效")
    if data["preview"] is not None or data["source_path"] is not None or data["source_page"] != 0:
        raise ChartPackageError("加密模板不允许本地源文件引用")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or type(data["calibrated"]) is not bool:
        raise ChartPackageError("模板版本或标定状态无效")
    size = data["reference_size"]
    if not isinstance(size,(list,tuple)) or len(size)!=2 or any(type(v) is not int or not 1<=v<=1_000_000 for v in size):
        raise ChartPackageError("模板参考尺寸无效")
    size = data["physical_size_mm"]
    if size is not None and (not isinstance(size,(list,tuple)) or len(size)!=2 or any(not _number(v) or not 0<v<=1_000_000 for v in size)):
        raise ChartPackageError("模板物理尺寸无效")
    if not isinstance(data["aliases"], list) or len(data["aliases"])>1000 or any(not isinstance(v,str) or len(v)>512 for v in data["aliases"]):
        raise ChartPackageError("模板别名无效")
    if not isinstance(data["regions"],list) or len(data["regions"])>MAX_REGIONS:
        raise ChartPackageError("模板测量区域过多或无效")
    if not isinstance(data["fiducials"],list) or len(data["fiducials"])>MAX_FIDUCIALS or any(not isinstance(v,dict) for v in data["fiducials"]):
        raise ChartPackageError("模板定位点过多或无效")
    for r in data["regions"]:
        if not isinstance(r,dict) or set(r)!=_REGION_FIELDS:
            raise ChartPackageError("测量区域字段无效")
        if not isinstance(r["id"],str) or not r["id"] or len(r["id"])>512 or not isinstance(r["kind"],str) or r["kind"] not in REGION_KINDS:
            raise ChartPackageError("测量区域标识或类型无效")
        if not isinstance(r["label"],str) or len(r["label"])>4096 or not isinstance(r["params"],dict) or type(r["enabled"]) is not bool:
            raise ChartPackageError("测量区域参数无效")
        if not isinstance(r["box"],(list,tuple)) or len(r["box"])!=4 or any(not _number(v) for v in r["box"]):
            raise ChartPackageError("测量区域坐标无效")
    for fiducial in data["fiducials"]:
        if "position" in fiducial:
            point=fiducial["position"]
            if not isinstance(point,(list,tuple)) or len(point)!=2 or any(not _number(v) or not 0<=v<=1 for v in point):
                raise ChartPackageError("模板定位点坐标无效")
        if fiducial.get("kind")=="usaf":
            if any(key not in fiducial for key in ("position","unit_id","k","direction","period_normalized")):
                raise ChartPackageError("USAF 定位点字段不完整")
            if not isinstance(fiducial["unit_id"],str) or not fiducial["unit_id"] or len(fiducial["unit_id"])>512 or type(fiducial["k"]) is not int or not -12<=fiducial["k"]<=65:
                raise ChartPackageError("USAF 定位点单元或频率无效")
            periods=fiducial["period_normalized"]
            if fiducial["direction"] not in ("vertical","horizontal") or not isinstance(periods,(list,tuple)) or len(periods)!=2 or any(not _number(v) or not 0<v<=1 for v in periods):
                raise ChartPackageError("USAF 定位点方向或周期无效")
    # Reject malicious path or embedded artwork metadata instead of quietly
    # importing different data from what the authenticated package contains.
    clean = _scrub(data)
    clean["source_path"] = None
    clean["preview"] = None
    if clean != data:
        raise ChartPackageError("模板数据含有禁止的文件路径或附件")
    try:
        ChartDefinition.from_dict(copy.deepcopy(data))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ChartPackageError("模板测量定义无效") from exc


def _png_bytes(image):
    # Rebuild from pixels so EXIF, text chunks, ICC, filenames and embedded
    # source attachments from a supplied preview cannot enter the export.
    rgb = image.convert("RGB")
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())
    stream = io.BytesIO()
    clean.save(stream, format="PNG", compress_level=1)
    data = stream.getvalue()
    if len(data)>MAX_IMAGE_BYTES:
        raise ChartPackageError("图卡栅格参考超过 32 MiB")
    return data


def _qimage_pil(image):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise ChartPackageError("无法生成图卡栅格参考")
    buffer.close()
    with Image.open(io.BytesIO(bytes(data))) as raster:
        return raster.convert("RGB")


def _reference_images(chart):
    from .templates import render_source
    image = None
    # Rasterize source locally without putting its content or path into the
    # payload. The high quality reference also preserves vector-USAF
    # orientation disambiguation when the original source is unavailable.
    if chart.source_path and Path(chart.source_path).is_file():
        try:
            raster, _, _ = render_source(chart.source_path, max_side=REFERENCE_MAX_SIDE, page=chart.source_page)
            image = _qimage_pil(raster)
        except (ValueError, OSError, RuntimeError):
            image = None
    if image is None and chart.preview and Path(chart.preview).is_file():
        try:
            raster, _, _ = render_source(chart.preview, max_side=REFERENCE_MAX_SIDE)
            image = _qimage_pil(raster)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ChartPackageError("无法读取图卡预览参考") from exc
    if image is None:
        from .demo import DEMO_ID, demo_definition, generate_frame
        if chart.id != DEMO_ID:
            raise ChartPackageError("图卡缺少可用的源文件或栅格预览；请先导入参考图")
        from .utils import to_rgb8
        image = Image.fromarray(to_rgb8(generate_frame(demo_definition(), .2)[0], linear=True))
    if min(image.size)<1 or max(image.size)>REFERENCE_MAX_SIDE:
        image.thumbnail((REFERENCE_MAX_SIDE,REFERENCE_MAX_SIDE),Image.Resampling.LANCZOS)
    reference = _png_bytes(image)
    thumb = image.copy()
    thumb.thumbnail((THUMBNAIL_MAX_SIDE,THUMBNAIL_MAX_SIDE),Image.Resampling.LANCZOS)
    return reference, _png_bytes(thumb)


def _validate_png(data, max_side):
    if not isinstance(data,bytes) or not 57<=len(data)<=MAX_IMAGE_BYTES or not data.startswith(_PNG):
        raise ChartPackageError("模板栅格参考不是有效 PNG")
    pos=8; compressed=[]; width=height=None; ended=False
    while pos<len(data):
        if pos+12>len(data):raise ChartPackageError("PNG 数据截断")
        length,kind=struct.unpack_from(">I4s",data,pos)
        end=pos+12+length
        if end>len(data) or length>MAX_IMAGE_BYTES:raise ChartPackageError("PNG 数据块过大或截断")
        chunk=data[pos+8:pos+8+length]
        crc=struct.unpack_from(">I",data,end-4)[0]
        if zlib.crc32(kind+chunk)&0xffffffff != crc:raise ChartPackageError("PNG 校验失败")
        if kind==b"IHDR" and pos==8 and length==13:
            width,height,bits,color,compression,filter_method,interlace=struct.unpack(">IIBBBBB",chunk)
            if not 1<=width<=max_side or not 1<=height<=max_side or bits!=8 or color!=2 or compression or filter_method or interlace:
                raise ChartPackageError("PNG 尺寸、像素格式或像素数超出限制")
        elif kind==b"IDAT" and width is not None:
            compressed.append(chunk)
        elif kind==b"IEND" and not length and compressed:
            ended=True;pos=end;break
        else:
            # Only RGB pixel chunks are accepted: no text/vector/EXIF payloads
            # hidden inside an otherwise legitimate PNG image.
            raise ChartPackageError("PNG 包含不允许的附件或数据块")
        pos=end
    if not ended or pos!=len(data):raise ChartPackageError("PNG 尾部或结构无效")
    decoder=zlib.decompressobj()
    expected=(width*3+1)*height
    try:
        raw=decoder.decompress(b"".join(compressed),expected+1)
    except zlib.error as exc:
        raise ChartPackageError("PNG 像素数据无效") from exc
    if len(raw)!=expected or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise ChartPackageError("PNG 解压像素大小不符或超出限制")
    try:
        with Image.open(io.BytesIO(data)) as raster:
            raster.load()
            if raster.mode!="RGB" or raster.size!=(width,height):raise ChartPackageError("PNG 像素格式无效")
    except (OSError, ValueError, SyntaxError) as exc:
        raise ChartPackageError("PNG 像素数据无法读取") from exc


def export_chart_package(chart, path, password):
    """Export a new .mxtpl without altering a source or overwriting any file.

    Keep the password separately: there is no recovery key. The package only
    carries raster registration references and validated measurement geometry.
    """
    secret=_password_bytes(password)
    target=Path(path).expanduser().absolute()
    if not target.suffix:target=target.with_suffix(PACKAGE_SUFFIX)
    if target.suffix.lower()!=PACKAGE_SUFFIX:raise ChartPackageError("加密图卡模板的后缀须为 .mxtpl")
    if target.exists() or target.is_symlink():raise FileExistsError(target)
    definition=_definition(chart)
    reference,thumbnail=_reference_images(chart)
    _validate_png(reference,REFERENCE_MAX_SIDE)
    _validate_png(thumbnail,THUMBNAIL_MAX_SIDE)
    payload=msgpack.packb({"format":"MUTEX Raster Chart", "version":1,
        "chart":definition, "reference_png":reference,"thumbnail_png":thumbnail},use_bin_type=True)
    if len(payload)>MAX_PAYLOAD_BYTES:raise ChartPackageError("模板数据超过 64 MiB")
    salt,nonce=os.urandom(16),os.urandom(12)
    manifest={"format":PACKAGE_FORMAT,"version":PACKAGE_VERSION,"cipher":"AES-256-GCM",
        "kdf":{"name":"Scrypt","n":_SCRYPT_N,"r":_SCRYPT_R,"p":_SCRYPT_P,
            "length":32,"salt":base64.b64encode(salt).decode("ascii")},
        "nonce":base64.b64encode(nonce).decode("ascii"),"payload_bytes":len(payload)+16}
    public=_json_bytes(manifest)
    ciphertext=AESGCM(_derive(secret,salt)).encrypt(nonce,payload,public)
    created=False
    try:
        # Exclusive creation also rejects a destination symlink/race. Do all
        # rendering and validation before creating this user-visible file.
        with target.open("xb") as stream:
            created=True
            with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=False) as archive:
                archive.writestr("manifest.json",public)
                archive.writestr("encrypted.bin",ciphertext)
            stream.flush();os.fsync(stream.fileno())
    except Exception:
        if created:target.unlink(missing_ok=True)
        raise
    return target


def _check_zip_directory(stream, size):
    # Bound the central directory before ZipFile parses it (otherwise a tiny
    # input with enormous entry counts can allocate many ZipInfo objects).
    if not 22<=size<=MAX_PACKAGE_BYTES:raise ChartPackageError("模板文件过大或不完整")
    stream.seek(max(0,size-65557));tail=stream.read(65557)
    offset=tail.rfind(b"PK\x05\x06")
    if offset<0 or offset+22>len(tail):raise ChartPackageError("不是完整 ZIP 模板")
    _,disk,cd_disk,disk_count,count,cd_size,cd_offset,comment=struct.unpack_from("<4s4H2IH",tail,offset)
    if disk or cd_disk or disk_count!=2 or count!=2 or cd_size>16384 or cd_offset+cd_size>size or offset+22+comment!=len(tail):
        raise ChartPackageError("模板 ZIP 目录无效或条目数量超出限制")
    stream.seek(0)


def _read_limited(archive, entry, limit):
    if not 0<=entry.file_size<=limit:raise ChartPackageError("模板 ZIP 展开大小超出限制")
    output=bytearray()
    with archive.open(entry,"r") as stream:
        while True:
            block=stream.read(min(65536,limit-len(output)+1))
            if not block:break
            output.extend(block)
            if len(output)>limit:raise ChartPackageError("模板 ZIP 展开大小超出限制")
    if len(output)!=entry.file_size:raise ChartPackageError("模板 ZIP 内容大小不符")
    return bytes(output)


def _manifest(data):
    try:
        value=json.loads(data.decode("ascii"),object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ChartPackageError("模板清单包含无效数字")))
    except (UnicodeError,ValueError,RecursionError) as exc:
        raise ChartPackageError("模板格式清单无效") from exc
    if not isinstance(value,dict) or set(value)!={"format","version","cipher","kdf","nonce","payload_bytes"}:
        raise ChartPackageError("模板格式清单字段无效")
    if value["format"]!=PACKAGE_FORMAT or type(value["version"]) is not int or value["version"]!=PACKAGE_VERSION or value["cipher"]!="AES-256-GCM":
        raise ChartPackageError("不支持的加密模板格式或版本")
    kdf=value["kdf"]
    if not isinstance(kdf,dict) or set(kdf)!={"name","n","r","p","length","salt"} or kdf["name"]!="Scrypt":
        raise ChartPackageError("模板密钥派生参数无效")
    if any(type(kdf[k]) is not int or kdf[k]!=expected for k,expected in (("n",_SCRYPT_N),("r",_SCRYPT_R),("p",_SCRYPT_P),("length",32))):
        raise ChartPackageError("模板密钥派生参数不受支持")
    try:
        salt=base64.b64decode(kdf["salt"],validate=True)
        nonce=base64.b64decode(value["nonce"],validate=True)
    except (ValueError,TypeError,binascii.Error) as exc:
        raise ChartPackageError("模板加密参数无效") from exc
    if len(salt)!=16 or len(nonce)!=12 or type(value["payload_bytes"]) is not int or not 17<=value["payload_bytes"]<=MAX_CIPHERTEXT_BYTES:
        raise ChartPackageError("模板加密参数长度无效")
    return value,salt,nonce


def _read_container(path):
    try:
        with Path(path).open("rb") as stream:
            size=os.fstat(stream.fileno()).st_size
            _check_zip_directory(stream,size)
            with zipfile.ZipFile(stream,"r") as archive:
                entries=archive.infolist()
                if len(entries)!=2 or {e.filename for e in entries}!=_ENTRIES or min(e.header_offset for e in entries)!=0:
                    raise ChartPackageError("模板 ZIP 只能含 manifest.json 和 encrypted.bin，不能有重复名或附加文件")
                if any(e.is_dir() or e.flag_bits&1 or e.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED} or len(e.extra)>4096 for e in entries):
                    raise ChartPackageError("模板 ZIP 条目类型不受支持")
                public=_read_limited(archive,archive.getinfo("manifest.json"),MAX_MANIFEST_BYTES)
                manifest,salt,nonce=_manifest(public)
                entry=archive.getinfo("encrypted.bin")
                if entry.file_size!=manifest["payload_bytes"]:raise ChartPackageError("模板密文长度不符")
                ciphertext=_read_limited(archive,entry,MAX_CIPHERTEXT_BYTES)
        return manifest,public,ciphertext,salt,nonce
    except (zipfile.BadZipFile,RuntimeError,EOFError,zlib.error,NotImplementedError,OverflowError) as exc:
        raise ChartPackageError("模板 ZIP 无效、损坏或超出展开限制") from exc


def inspect_chart_package(path):
    """Validate the container and return public format metadata, without a key.

    The returned manifest is structurally checked but becomes authenticated
    only after load_chart_package successfully verifies the AES-GCM tag.
    """
    return copy.deepcopy(_read_container(path)[0])


def _decode_payload(payload):
    if len(payload)>MAX_PAYLOAD_BYTES:raise ChartPackageError("解密后的模板过大")
    try:
        data=msgpack.unpackb(payload,raw=False,strict_map_key=True,object_pairs_hook=_unique_pairs,
            max_str_len=65536,max_bin_len=MAX_IMAGE_BYTES,max_array_len=200000,
            max_map_len=100000,max_ext_len=0)
    except (ValueError,TypeError,RecursionError,msgpack.exceptions.StackError) as exc:
        raise ChartPackageError("模板二进制结构无效") from exc
    if not isinstance(data,dict) or set(data)!={"format","version","chart","reference_png","thumbnail_png"} or data["format"]!="MUTEX Raster Chart" or type(data["version"]) is not int or data["version"]!=1:
        raise ChartPackageError("模板二进制格式或版本不受支持")
    definition=data["chart"]
    _validate_definition(definition)
    if len(msgpack.packb(definition,use_bin_type=True))>MAX_DEFINITION_BYTES:raise ChartPackageError("模板定义超过 16 MiB")
    _validate_png(data["reference_png"],REFERENCE_MAX_SIDE)
    _validate_png(data["thumbnail_png"],THUMBNAIL_MAX_SIDE)
    return definition,data["reference_png"],data["thumbnail_png"]


def _cache_images(root, reference, thumbnail):
    root=Path(root).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(reference+b"\x00"+thumbnail).hexdigest()
    destination=root/("mxtpl-"+key)
    expected={"reference.png":reference,"thumbnail.png":thumbnail}
    def existing():
        if destination.is_symlink() or not destination.is_dir():raise ChartPackageError("模板缓存目录无效")
        for name,content in expected.items():
            p=destination/name
            if p.is_symlink() or not p.is_file() or p.stat().st_size!=len(content) or p.read_bytes()!=content:
                raise ChartPackageError("同名模板缓存内容损坏，请清理后重新导入")
        return destination/"reference.png"
    if destination.exists() or destination.is_symlink():return existing()
    temporary=Path(tempfile.mkdtemp(prefix=".mxtpl-",dir=root)).resolve()
    if not temporary.is_relative_to(root):raise ChartPackageError("模板缓存路径无效")
    try:
        for name,content in expected.items():
            with (temporary/name).open("xb") as stream:stream.write(content)
        try:temporary.rename(destination)
        except OSError:
            if not destination.exists():raise
            return existing()
        return destination/"reference.png"
    finally:
        # Delete only our two explicit temporary files, never recursively walk
        # the library or remove a pre-existing shared registration reference.
        if temporary.exists():
            for name in expected:(temporary/name).unlink(missing_ok=True)
            temporary.rmdir()


def load_chart_package(path, password, cache_dir=None):
    """Authenticate/import a .mxtpl and return a source-independent definition.

    No file is extracted before authentication, schema and bounded PNG checks.
    cache_dir defaults to the private user chart library's previews directory.
    The returned chart references cached raster working data, never SVG/PDF.
    """
    secret=_password_bytes(password)
    _,public,ciphertext,salt,nonce=_read_container(path)
    try:payload=AESGCM(_derive(secret,salt)).decrypt(nonce,ciphertext,public)
    except InvalidTag as exc:
        raise ChartPackagePasswordError("模板口令不正确，或文件已被篡改/损坏") from exc
    definition,reference,thumbnail=_decode_payload(payload)
    if cache_dir is None:
        from .templates import library_dir
        cache_dir=library_dir()/"previews"
    preview=_cache_images(cache_dir,reference,thumbnail)
    definition=copy.deepcopy(definition)
    definition["source_path"]=None
    definition["preview"]=str(preview)
    return ChartDefinition.from_dict(definition)
