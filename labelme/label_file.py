import base64
import contextlib
import io
import json
import os.path as osp
import os
import re

import PIL.Image

from labelme import PY2
from labelme import QT4
from labelme import __version__
from labelme import utils
from labelme.logger import logger

PIL.Image.MAX_IMAGE_PIXELS = None

@contextlib.contextmanager
def open(name, mode):
    assert mode in ["r", "w"]
    if PY2:
        mode += "b"
        encoding = None
    else:
        encoding = "utf-8"
    yield io.open(name, mode, encoding=encoding)
    return

class LabelFileError(Exception):
    pass

class LabelFile(object):
    suffix = ".json"

    def __init__(self, filename=None):
        self.shapes = []
        self.imagePath = None
        self.imageData = None
        if filename is not None:
            self.load(filename)
        self.filename = filename

    @staticmethod
    def load_image_file(filename):
        try:
            image_pil = PIL.Image.open(filename)
        except IOError:
            logger.error("Failed opening image file: {}".format(filename))
            return

        # apply orientation to image according to exif
        image_pil = utils.apply_exif_orientation(image_pil)

        with io.BytesIO() as f:
            ext = osp.splitext(filename)[1].lower()
            if PY2 and QT4:
                format = "PNG"
            elif ext in [".jpg", ".jpeg"]:
                format = "JPEG"
            else:
                format = "PNG"
            image_pil.save(f, format=format)
            f.seek(0)
            return f.read()

    def load(self, filename):
        keys = [
            "version",
            "imageData",
            "imagePath",
            "shapes",  # polygonal annotations
            "flags",  # image level flags
            "imageHeight",
            "imageWidth",
            "date",  # added for date
            "latitude",  # added for latitude
            "longitude",  # added for longitude
        ]
        shape_keys = [
            "label",
            "points",
            "group_id",
            "shape_type",
            "flags",
            "description",
            "mask",
        ]
        try:
            with open(filename, "r") as f:
                data = json.load(f)

            if data["imageData"] is not None:
                imageData = base64.b64decode(data["imageData"])
                if PY2 and QT4:
                    imageData = utils.img_data_to_png_data(imageData)
            else:
                # relative path from label file to relative path from cwd
                imagePath = osp.join(osp.dirname(filename), data["imagePath"])
                imageData = self.load_image_file(imagePath)
            flags = data.get("flags") or {}
            imagePath = data["imagePath"]
            self._check_image_height_and_width(
                base64.b64encode(imageData).decode("utf-8"),
                data.get("imageHeight"),
                data.get("imageWidth"),
            )
            shapes = [
                dict(
                    label=s["label"],
                    points=s["points"],
                    shape_type=s.get("shape_type", "polygon"),
                    flags=s.get("flags", {}),
                    description=s.get("description"),
                    group_id=s.get("group_id"),
                    mask=utils.img_b64_to_arr(s["mask"]).astype(bool)
                    if s.get("mask")
                    else None,
                    other_data={k: v for k, v in s.items() if k not in shape_keys},
                )
                for s in data["shapes"]
            ]
        except Exception as e:
            raise LabelFileError(e)

        otherData = {}
        for key, value in data.items():
            if key not in keys:
                otherData[key] = value

        # Only replace data after everything is loaded.
        self.flags = flags
        self.shapes = shapes
        self.imagePath = imagePath
        self.imageData = imageData
        self.filename = filename
        self.otherData = otherData
        self.date = data.get("date", None)
        self.latitude = data.get("latitude", None)
        self.longitude = data.get("longitude", None)

    @staticmethod
    def _check_image_height_and_width(imageData, imageHeight, imageWidth):
        img_arr = utils.img_b64_to_arr(imageData)
        if imageHeight is not None and img_arr.shape[0] != imageHeight:
            logger.error(
                "imageHeight does not match with imageData or imagePath, "
                "so getting imageHeight from actual image."
            )
            imageHeight = img_arr.shape[0]
        if imageWidth is not None and img_arr.shape[1] != imageWidth:
            logger.error(
                "imageWidth does not match with imageData or imagePath, "
                "so getting imageWidth from actual image."
            )
            imageWidth = img_arr.shape[1]
        return imageHeight, imageWidth

    def save(
        self,
        filename,
        shapes,
        imagePath,
        imageHeight,
        imageWidth,
        imageData=None,
        otherData=None,
        flags=None,
    ):
        # print("saving")

        # ���ϸ��� Ȯ���� ����
        file_name_without_extension = osp.splitext(imagePath)[0]

        # ���� ���丮�� ���ϸ��� �����Ͽ� ��ġ ���� ����
        base_dir = osp.basename(osp.dirname(filename))
        parts = file_name_without_extension.split('_')

        try:
            # �浵�� ���� ����
            longitude = parts[-3]  # �浵
            latitude = parts[-4]   # ����
            date_str = parts[-6]   # ��¥ (��: 2018.11)

            # ��¥ ���ڿ����� ������ �� �и�
            year, month = date_str.split('.')
            date = {"year": year, "month": month}
        except (IndexError, ValueError):
            # �⺻�� ����
            date = {"year": "", "month": ""}
            latitude = ""
            longitude = ""

        # Save in the original format!!!
        if imageData is not None:
            imageData = base64.b64encode(imageData).decode("utf-8")
            imageHeight, imageWidth = self._check_image_height_and_width(
                imageData, imageHeight, imageWidth
            )
        if otherData is None:
            otherData = {}
        if flags is None:
            flags = {}
        data = dict(
            version=__version__,
            flags=flags,
            shapes=shapes,
            imagePath=imagePath,
            imageData=imageData,
            imageHeight=imageHeight,
            imageWidth=imageWidth,
        )
        for key, value in otherData.items():
            assert key not in data
            data[key] = value
        try:
            with open(filename, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise LabelFileError(e)


        # Save in the new format!!!
        # {base_dir}_labeled ���� ��� ����
        labeled_dir = osp.join(osp.dirname(osp.dirname(filename)), f"{base_dir}_labeled")
        if not osp.exists(labeled_dir):
            os.makedirs(labeled_dir)
            
        # ���ο� ���ϸ� ����
        new_filename = osp.join(labeled_dir, osp.basename(filename))
            
        #new_filename = filename.replace(".json", "_new.json")

        # Create new data dictionary with the specified format
        new_data = dict(
            version=__version__,
            flags=flags,
            shapes=[
                {
                    "points": shape.get("points"),
                    "shape_type": shape.get("shape_type"),
                    "class": shape.get("label"),  # ���� 'label'�� value�� 'class'�� ����
                    "location_id": f"id_{base_dir}_{str(shape.get('group_id', 'unknown')).zfill(3)}"
                }
                for shape in shapes
            ],
            imagePath=imagePath,
            imageData=imageData if imageData else "",
            imageHeight=imageHeight,
            imageWidth=imageWidth,
            date=date,
            latitude=latitude,
            longitude=longitude,
        )

        # Add any additional data from otherData
        for key, value in otherData.items():
            assert key not in new_data
            new_data[key] = value

        try:
            with open(new_filename, "w") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
                print(f"Saving JSON file to: {new_filename}")
        except Exception as e:
            raise LabelFileError(e)
        

        # Save in the new format2!!!
        # {base_dir}_labeled_formatted ���� ��� ����
        labeled_formatted_dir = osp.join(osp.dirname(osp.dirname(filename)), f"{base_dir}_labeled_formatted")
    
        if not osp.exists(labeled_formatted_dir):
            os.makedirs(labeled_formatted_dir)

        new_filename2 = osp.join(labeled_formatted_dir, osp.basename(filename))
        #new_filename2 = filename.replace(".json", "_new2.json")
        
        # Create new data dictionary with the specified format
        new_data2 = dict(
            version=__version__,
            flags=flags,
            shapes=[
                {
                    "label": shape.get("label"),  # ���� 'label'�� value�� 'class'�� ����
                    "points": shape.get("points"),
                    "group_id": shape.get("group_id", "unknown"),  # 'group_id'�� ������ 'unknown' ���
                    "description": shape.get("description", ""),
                    "shape_type": shape.get("shape_type"),
                    "flags": shape.get("flags", {}),
                }
                for shape in shapes
            ],
            imagePath=imagePath,
            imageData=imageData if imageData else "",
            imageHeight=imageHeight,
            imageWidth=imageWidth,
        )
        
        # Add any additional data from otherData
        for key, value in otherData.items():
            assert key not in new_data2
            new_data2[key] = value

        try:
            with open(new_filename2, "w") as f:
                json.dump(new_data2, f, ensure_ascii=False, indent=2)
                print(f"Saving JSON file to: {new_filename2}")
        except Exception as e:
            raise LabelFileError(e)

    @staticmethod
    def is_label_file(filename):
        return osp.splitext(filename)[1].lower() == LabelFile.suffix
