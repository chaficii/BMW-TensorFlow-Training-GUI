from application.data_preparation.models.tf_record_path import TfRecordPath
from application.paths.services.path_service import PathService
from domain.exceptions.data_preparation_exception import TfrecordsInvalid
from domain.models.paths import Paths
from domain.services.contract.abstract_tfrecords_generator_service import AbstractTfRecordGeneratorService
import json
import os
import pandas as pd
import io

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Suppress TensorFlow logging (1)
import tensorflow.compat.v1 as tf
from typing import Dict, List, NamedTuple, Tuple, Any
from PIL import Image
from object_detection.utils import dataset_util, label_map_util
from collections import namedtuple


class TfRecordGeneratorService(AbstractTfRecordGeneratorService):
    """
     A class used to create tf records

    ...

     Attributes
    ----------
    path : Paths
        DTO containing all necessary paths
    label_map_dict : Dict[str,int]
        dict to store class and corresponding id
    Methods
    -------
    generate_tf_record(tf_record_path: TfRecordPath) -> None
        generate tf records using TF internal function and taking as input the train,test csv
    """

    def __init__(self, path: PathService):
        self.path: Paths = path.get_paths()
        self.label_map_dict: Dict[str, int] = {}

    def _initialize_label_map(self) -> None:
        label_map = label_map_util.load_labelmap(self.path.label_map_path)
        self.label_map_dict: Dict[str, int] = label_map_util.get_label_map_dict(label_map)
        
    def _class_text_to_int(self, row_label) -> int:
        return self.label_map_dict[row_label]

    def _split(self, df: pd.DataFrame, group: str) -> List[Any]:
        data: NamedTuple = namedtuple('data', ['filename', 'object'])
        df_grouped = dict(tuple(df.groupby(group)))
        return [data(filename, x) for filename, x in df_grouped.items()]

    def _create_tf_example(self, group, path):
        with tf.gfile.GFile(os.path.join(path, '{}'.format(group.filename)), 'rb') as fid:
            encoded_jpg = fid.read()

        # get the width and height from the first element because all element are from the same image
        index, obj = next(iter(group.object.iterrows()))
        width, height = obj["width"], obj["height"]

        filename = group.filename.encode('utf8')
        image_format = b'jpg'
        xmins: List[float] = list(map(lambda x: x / width, group.object['xmin'].tolist()))
        xmaxs: List[float] = list(map(lambda x: x / width, group.object['xmax'].tolist()))
        ymins: List[float] = list(map(lambda x: x / height, group.object['ymin'].tolist()))
        ymaxs: List[float] = list(map(lambda x: x / height, group.object['ymax'].tolist()))
        classes_text: List[str] = list(map(lambda x: x.encode('utf8'), group.object['class'].tolist()))
        classes: List[int] = list(map(lambda x: self._class_text_to_int(x), group.object['class'].tolist()))

        tf_example = tf.train.Example(features=tf.train.Features(feature={
            'image/height': dataset_util.int64_feature(height),
            'image/width': dataset_util.int64_feature(width),
            'image/filename': dataset_util.bytes_feature(filename),
            'image/source_id': dataset_util.bytes_feature(filename),
            'image/encoded': dataset_util.bytes_feature(encoded_jpg),
            'image/format': dataset_util.bytes_feature(image_format),
            'image/object/bbox/xmin': dataset_util.float_list_feature(xmins),
            'image/object/bbox/xmax': dataset_util.float_list_feature(xmaxs),
            'image/object/bbox/ymin': dataset_util.float_list_feature(ymins),
            'image/object/bbox/ymax': dataset_util.float_list_feature(ymaxs),
            'image/object/class/text': dataset_util.bytes_list_feature(classes_text),
            'image/object/class/label': dataset_util.int64_list_feature(classes),
        }))
        return tf_example

    def generate_tf_record(self, tf_record_path: TfRecordPath) -> None:
        try:
            writer = tf.python_io.TFRecordWriter(tf_record_path.output_path)
            self._initialize_label_map()

            examples: pd.DataFrame = pd.read_csv(tf_record_path.input_path)

            grouped = self._split(df=examples, group='filename')
            for group in grouped:
                tf_example = self._create_tf_example(group, self.path.images_dir)
                writer.write(tf_example.SerializeToString())
            writer.close()
        except Exception as e:
            raise TfrecordsInvalid(additional_message=e.__str__())
