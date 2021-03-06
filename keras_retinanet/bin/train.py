#!/usr/bin/env python

"""
Copyright 2017-2018 Fizyr (https://fizyr.com)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import os
import sys
import warnings

import keras
import keras.preprocessing.image
import tensorflow as tf
from imgaug import augmenters as iaa

# Allow relative imports when being executed as script.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    import keras_retinanet.bin  # noqa: F401
    __package__ = "keras_retinanet.bin"

# Change these to absolute imports if you copy this script outside the keras_retinanet package.
from .. import layers  # noqa: F401
from .. import losses
from .. import models
from ..attrdict import AttrDict
from ..callbacks import RedirectModel
from ..callbacks.eval import Evaluate
from ..models.retinanet import retinanet_bbox
from ..preprocessing.csv_generator import CSVGenerator
from ..preprocessing.kitti import KittiGenerator
from ..preprocessing.open_images import OpenImagesGenerator
from ..preprocessing.pascal_voc import PascalVocGenerator
from ..utils.anchors import make_shapes_callback
from ..utils.keras_version import check_keras_version
from ..utils.model import freeze as freeze_model
from ..utils.transform import random_transform_generator
sys.path.append('/repos/kerastrainutils')
from callbacks import CSVWallClockLogger
def makedirs(path):
    # Intended behavior: try to create the directory,
    # pass if the directory exists already, fails otherwise.
    # Meant for Python 2.7/3.n compatibility.
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise


def get_session():
    """ Construct a modified tf session.
    """
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    return tf.Session(config=config)


def model_with_weights(model, weights, skip_mismatch):
    """ Load weights for model.

    Args
        model         : The model to load weights for.
        weights       : The weights to load.
        skip_mismatch : If True, skips layers whose shape of weights doesn't match with the model.
    """
    if weights is not None:
        model.load_weights(weights, by_name=True, skip_mismatch=skip_mismatch)
    return model


def create_models(backbone_retinanet, num_classes, weights, multi_gpu=0, 
                  skip_mismatch=True,
                  freeze_backbone=False, lr=1e-5,
                  score_threshold       = 0.05,
                  max_detections        = 300,
                  nms_threshold         = 0.5,
                  alpha=0.25, gamma=2.0,
                  share_rpn=True,
                  class_feature_sizes   = [256]*4,
                  regr_feature_sizes    = [256]*4,
                  common_feature_sizes  = [],
                  coordconv             = False,
                  submodels             = None):
    """ Creates three models (model, training_model, prediction_model).

    Args
        backbone_retinanet : A function to call to create a retinanet model with a given backbone.
        num_classes        : The number of classes to train.
        weights            : The weights to load into the model.
        multi_gpu          : The number of GPUs to use for training.
        freeze_backbone    : If True, disables learning for the backbone.

    Returns
        model            : The base model. This is also the model that is saved in snapshots.
        training_model   : The training model. If multi_gpu=0, this is identical to model.
        prediction_model : The model wrapped with utility functions to perform object detection (applies regression values and performs NMS).
    """
    modifier = freeze_model if freeze_backbone else None

    # Keras recommends initialising a multi-gpu model on the CPU to ease weight sharing, and to prevent OOM errors.
    # optionally wrap in a parallel model
    #import ipdb; ipdb.set_trace()
    if multi_gpu > 1:
        from keras.utils import multi_gpu_model
        with tf.device('/cpu:0'):
            model = model_with_weights(backbone_retinanet(num_classes, modifier=modifier), 
                                       weights=weights, skip_mismatch=skip_mismatch)
        training_model = multi_gpu_model(model, gpus=multi_gpu)
    else:
        # this instantiates the model
        retinanet = backbone_retinanet(num_classes, modifier=modifier, submodels=submodels,
                                      share_rpn=share_rpn,
                                      class_feature_sizes = class_feature_sizes,
                                      regr_feature_sizes  = regr_feature_sizes,
                                      common_feature_sizes  = common_feature_sizes,
                                      coordconv = coordconv,
                                      )
        model = model_with_weights(retinanet, weights=weights, skip_mismatch=skip_mismatch)
        training_model = model

    # make prediction model
    prediction_model = retinanet_bbox(model=model,
                                      score_threshold       = score_threshold,
                                      max_detections        = max_detections,
                                      nms_threshold         = nms_threshold,
                                      )

    # compile model
    training_model.compile(
        loss={
            'regression'    : losses.smooth_l1(),
            'classification': losses.focal(alpha=alpha, gamma=gamma)
        },
        optimizer=keras.optimizers.adam(lr=lr, clipnorm=0.001)
    )

    return model, training_model, prediction_model


def create_callbacks(model, training_model, prediction_model, validation_generator, args,
    lr_drop_factor=0.5, lr_patience=2):
    """ Creates the callbacks to use during training.

    Args
        model: The base model.
        training_model: The model that is used for training.
        prediction_model: The model that should be used for validation.
        validation_generator: The generator for creating validation data.
        args: parseargs args object.

    Returns:
        A list of callbacks used for training.
    """
    callbacks = []

    tensorboard_callback = None

    if args.snapshots:
        save_dir = os.path.join(args.snapshot_path, args.md5)
    else:
        save_dir = 'snapshots'

    if args.tensorboard_dir:
        tensorboard_callback = keras.callbacks.TensorBoard(
            log_dir                = save_dir, #args.tensorboard_dir,
            histogram_freq         = 0,
            batch_size             = args.batch_size,
            write_graph            = True,
            write_grads            = False,
            write_images           = False,
            embeddings_freq        = 0,
            embeddings_layer_names = None,
            embeddings_metadata    = None
        )
        callbacks.append(tensorboard_callback)

    if args.evaluation and validation_generator:
        if args.dataset_type == 'coco':
            from ..callbacks.coco import CocoEval

            # use prediction model for evaluation
            evaluation = CocoEval(validation_generator, tensorboard=tensorboard_callback,
				  resdir=save_dir)
        else:
            evaluation = Evaluate(validation_generator, tensorboard=tensorboard_callback)
        evaluation = RedirectModel(evaluation, prediction_model)
        callbacks.append(evaluation)
        csv_filename = os.path.join(save_dir, 'progress.csv')
        callbacks.append(CSVWallClockLogger(csv_filename))

    # save the model
    if args.snapshots:
        # ensure directory created first; otherwise h5py will error after epoch.
        #save_dir = os.path.join(args.snapshot_path, args.md5)
        makedirs(save_dir)
        args.to_yaml(os.path.join(save_dir, "run.info"))
        checkpoint = keras.callbacks.ModelCheckpoint(
            os.path.join(
                save_dir,
                '{backbone}_{dataset_type}_{{epoch:02d}}.h5'.format(backbone=args.backbone, dataset_type=args.dataset_type)
            ),
            verbose=1,
            # save_best_only=True,
            # monitor="mAP",
            # mode='max'
        )
        checkpoint = RedirectModel(checkpoint, model)
        callbacks.append(checkpoint)

    callbacks.append(keras.callbacks.ReduceLROnPlateau(
        monitor  = 'loss',
        factor   = lr_drop_factor,
        patience = lr_patience,
        verbose  = 1,
        mode     = 'auto',
        epsilon  = 0.0001,
        cooldown = 0,
        min_lr   = 0
    ))

    return callbacks

def create_homogenous_augm_wrapper(args):
    seq = []
    if args.freq_gaussian_noise > 0.0:
        seq.append( iaa.Sometimes(args.freq_gaussian_noise, iaa.AdditiveGaussianNoise(scale=0.05*255, per_channel=0.25)) )
    if args.freq_gaussian_blur > 0.0:
        seq.append( iaa.Sometimes(args.freq_gaussian_blur, iaa.GaussianBlur(sigma=args.sigma_gaussian_blur)) )
    if args.freq_hue_sat > 0.0:
        # change hue and saturation
        sometimes = lambda aug: iaa.Sometimes(args.freq_hue_sat, aug)
        seq.append( sometimes(iaa.AddToHueAndSaturation((-args.hue_sat, args.hue_sat))) )

    if args.freq_sharpen >0.0:
        seq.append( iaa.Sometimes(args.freq_sharpen, iaa.Sharpen(alpha=args.sigma_sharpen)) )
    if len(seq)>0:    
        seq = iaa.Sequential(seq, random_order=True)
        print("Augmenting with color/brightness/noise")
        print(seq)
    else:
        seq = None

    def homogenous_augm_wrapper(gen):
        print('gen has next:', hasattr(gen, '__next__'))
        #import ipdb; ipdb.set_trace()
        for img, ann in gen:
            if seq is not None:
                img = seq.augment_images(img)
            yield img, ann
    return homogenous_augm_wrapper

def create_generators(args, preprocess_image):
    """ Create generators for training and validation.

    Args
        args             : parseargs object containing configuration for generators.
        preprocess_image : Function that preprocesses an image for the network.
    """
    common_args = {
        'batch_size'       : args.batch_size,
        'image_min_side'   : args.image_min_side,
        'image_max_side'   : args.image_max_side,
        'preprocess_image' : preprocess_image,
    }

        

    # create random transform generator for augmenting training data
    if args.random_transform:
        flip_x_chance = 0.5 if args.flip_x else 0.0
        flip_y_chance = 0.5 if args.flip_y else 0.0

        transform_generator = random_transform_generator(
            min_rotation=-0.1,
            max_rotation=0.1,
            min_translation=(-0.1, -0.1),
            max_translation=(0.1, 0.1),
            min_shear=-0.1,
            max_shear=0.1,
            min_scaling=(0.9, 0.9),
            max_scaling=(1.1, 1.1),
            flip_x_chance=flip_x_chance,
            flip_y_chance=flip_y_chance,
        )
    else:
        transform_generator = random_transform_generator(flip_x_chance=0.5)

    if args.dataset_type == 'coco':
        # import here to prevent unnecessary dependency on cocoapi
        from ..preprocessing.coco import CocoGenerator

        train_generator = CocoGenerator(
            args.coco_path,
            'train2017',
            transform_generator=transform_generator,
            order=args.order,
            **common_args
        )

        validation_generator = CocoGenerator(
            args.coco_path,
            'val2017',
            order=args.order,
            **common_args
        )

        #import ipdb; ipdb.set_trace()
    elif args.dataset_type == 'pascal':
        train_generator = PascalVocGenerator(
            args.pascal_path,
            'trainval',
            transform_generator=transform_generator,
            **common_args
        )

        validation_generator = PascalVocGenerator(
            args.pascal_path,
            'test',
            **common_args
        )
    elif args.dataset_type == 'csv':
        train_generator = CSVGenerator(
            args.annotations,
            args.classes,
            transform_generator=transform_generator,
            **common_args
        )

        if args.val_annotations:
            validation_generator = CSVGenerator(
                args.val_annotations,
                args.classes,
                **common_args
            )
        else:
            validation_generator = None
    elif args.dataset_type == 'oid':
        train_generator = OpenImagesGenerator(
            args.main_dir,
            subset='train',
            version=args.version,
            labels_filter=args.labels_filter,
            annotation_cache_dir=args.annotation_cache_dir,
            parent_label=args.parent_label,
            transform_generator=transform_generator,
            **common_args
        )

        validation_generator = OpenImagesGenerator(
            args.main_dir,
            subset='validation',
            version=args.version,
            labels_filter=args.labels_filter,
            annotation_cache_dir=args.annotation_cache_dir,
            parent_label=args.parent_label,
            **common_args
        )
    elif args.dataset_type == 'kitti':
        train_generator = KittiGenerator(
            args.kitti_path,
            subset='train',
            transform_generator=transform_generator,
            **common_args
        )

        validation_generator = KittiGenerator(
            args.kitti_path,
            subset='val',
            **common_args
        )
    else:
        raise ValueError('Invalid data type received: {}'.format(args.dataset_type))

    return train_generator, validation_generator


def check_args(parsed_args):
    """ Function to check for inherent contradictions within parsed arguments.
    For example, batch_size < num_gpus
    Intended to raise errors prior to backend initialisation.

    Args
        parsed_args: parser.parse_args()

    Returns
        parsed_args
    """

    if parsed_args.multi_gpu > 1 and parsed_args.batch_size < parsed_args.multi_gpu:
        raise ValueError(
            "Batch size ({}) must be equal to or higher than the number of GPUs ({})".format(parsed_args.batch_size,
                                                                                             parsed_args.multi_gpu))

    if parsed_args.multi_gpu > 1 and parsed_args.snapshot:
        raise ValueError(
            "Multi GPU training ({}) and resuming from snapshots ({}) is not supported.".format(parsed_args.multi_gpu,
                                                                                                parsed_args.snapshot))

    if parsed_args.multi_gpu > 1 and not parsed_args.multi_gpu_force:
        raise ValueError("Multi-GPU support is experimental, use at own risk! Run with --multi-gpu-force if you wish to continue.")

    if 'resnet' not in parsed_args.backbone:
        warnings.warn('Using experimental backbone {}. Only resnet50 has been properly tested.'.format(parsed_args.backbone))

    return parsed_args


def parse_args(args):
    """ Parse the arguments.
    """
    parser     = argparse.ArgumentParser(description='Simple training script for training a RetinaNet network.')
    subparsers = parser.add_subparsers(help='Arguments for specific dataset types.', dest='dataset_type')
    subparsers.required = True

    coco_parser = subparsers.add_parser('coco')
    coco_parser.add_argument('coco_path', help='Path to dataset directory (ie. /tmp/COCO).')

    pascal_parser = subparsers.add_parser('pascal')
    pascal_parser.add_argument('pascal_path', help='Path to dataset directory (ie. /tmp/VOCdevkit).')

    kitti_parser = subparsers.add_parser('kitti')
    kitti_parser.add_argument('kitti_path', help='Path to dataset directory (ie. /tmp/kitti).')

    def csv_list(string):
        return string.split(',')

    oid_parser = subparsers.add_parser('oid')
    oid_parser.add_argument('main_dir', help='Path to dataset directory.')
    oid_parser.add_argument('--version',  help='The current dataset version is v4.', default='v4')
    oid_parser.add_argument('--labels-filter',  help='A list of labels to filter.', type=csv_list, default=None)
    oid_parser.add_argument('--annotation-cache-dir', help='Path to store annotation cache.', default='.')
    oid_parser.add_argument('--parent-label', help='Use the hierarchy children of this label.', default=None)

    csv_parser = subparsers.add_parser('csv')
    csv_parser.add_argument('annotations', help='Path to CSV file containing annotations for training.')
    csv_parser.add_argument('classes', help='Path to a CSV file containing class label mapping.')
    csv_parser.add_argument('--val-annotations', help='Path to CSV file containing annotations for validation (optional).')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--snapshot',          help='Resume training from a snapshot.')
    group.add_argument('--imagenet-weights',  help='Initialize the model with pretrained imagenet weights. This is the default behaviour.', action='store_const', const=True, default=True)
    group.add_argument('--weights',           help='Initialize the model with weights from a file.')
    group.add_argument('--no-weights',        help='Don\'t initialize the model with any weights.', dest='imagenet_weights', action='store_const', const=False)

    parser.add_argument('--lr',              help='learning rate.', type=float, default=1e-5)
    parser.add_argument('--loss-alpha',      help='learning rate.', type=float, default=0.25)
    parser.add_argument('--loss-gamma',      help='learning rate.', type=float, default=2.0)
    parser.add_argument('--backbone',        help='Backbone model used by retinanet.', default='resnet50', type=str)
    parser.add_argument('--preprocess-mode', help='Preprocessing mode : {"caffe", "tf", "none"}', default='caffe', type=str)
    parser.add_argument('--batch-size',      help='Size of the batches.', default=1, type=int)
    parser.add_argument('--gpu',             help='Id of the GPU to use (as reported by nvidia-smi).')
    parser.add_argument('--multi-gpu',       help='Number of GPUs to use for parallel processing.', type=int, default=0)
    parser.add_argument('--multi-gpu-force', help='Extra flag needed to enable (experimental) multi-gpu support.', action='store_true')
    parser.add_argument('--epochs',          help='Number of epochs to train.', type=int, default=50)
    parser.add_argument('--steps',           help='Number of steps per epoch.', type=int, default=10000)
    parser.add_argument('--lr-patience',     help='', type=int, default=2)
    parser.add_argument('--lr-drop-factor',  help='', type=float, default=.5)
    parser.add_argument('--snapshot-path',   help='Path to store snapshots of models during training (defaults to \'./snapshots\')', default='./snapshots')
    parser.add_argument('--tensorboard-dir', help='Log directory for Tensorboard output', default='./logs')
    parser.add_argument('--no-snapshots',    help='Disable saving snapshots.', dest='snapshots', action='store_false')
    parser.add_argument('--no-evaluation',   help='Disable per epoch evaluation.', dest='evaluation', action='store_false')
    parser.add_argument('--freeze-backbone', help='Freeze training of backbone layers.', action='store_true')
    parser.add_argument('--no-share-rpn', help='Share weights between RPN networks.', action='store_false', dest='share_rpn')
    parser.add_argument('--class-feature-sizes', nargs='+', type=int, default=[256]*4)
    parser.add_argument('--regr-feature-sizes', nargs='+', type=int, default=[256]*4)
    parser.add_argument('--common-feature-sizes', nargs='+', type=int, default=[])
    parser.add_argument('--coordconv', help='apply Coord Conv', action='store_true')
    parser.add_argument('--random-transform', help='Randomly transform image and annotations.', action='store_true')
    parser.add_argument('--flip-x', help='Randomly flip LR image and annotations.', action='store_true')
    parser.add_argument('--flip-y', help='Randomly flip UD image and annotations.', action='store_true')
    parser.add_argument('--image-min-side', help='Rescale the image so the smallest side is min_side.', type=int, default=512)
    parser.add_argument('--image-max-side', help='Rescale the image if the largest side is larger than max_side.', type=int, default=1333)
    parser.add_argument('--order', help='color channel order', type=str, default='bgr')
    parser.add_argument('--submodels', help='None|joint_submodels|', type=str, default=None)
    parser.add_argument('--score-threshold',      help='', type=float, default=0.05)
    parser.add_argument('--nms-threshold',      help='', type=float, default=0.5)
    parser.add_argument('--max-detections',      help='', type=int, default=300)
    parser.add_argument('--freq-gaussian-noise', help='frequency of random augmentation: noise', type=float, default=0.0)  
    parser.add_argument('--freq-gaussian-blur',  help='frequency of random augmentation: blur',  type=float, default=0.0) 
    parser.add_argument('--freq-hue-sat',        help='frequency of random augmentation: hue/saturation', type=float, default=0.0)
    parser.add_argument('--freq-sharpen',        help='frequency of random augmentation: sharpening', type=float, default=0.0) 
    parser.add_argument('--hue-sat',             help='', type=float, default=30.0) 
    parser.add_argument('--sigma-gaussian-blur', help='', type=float, default=[0.0, 2.0], nargs='+')
    parser.add_argument('--sigma-sharpen',       help='', type=float, default=[0.0, 1.0], nargs='+')

    return check_args(parser.parse_args(args))

from tensorflow.python.client import device_lib

def get_available_gpus():
    local_device_protos = device_lib.list_local_devices()
    return [x.name for x in local_device_protos if x.device_type == 'GPU']

def main(args=None):
    print("GPUS:", get_available_gpus())

    # parse arguments
    if args is None:
        args = sys.argv[1:]
    args = parse_args(args)
    args = AttrDict(args.__dict__)
    args.add_git()
    arghash = args.md5
    print("argument hash:", arghash)

    # create object that stores backbone information
    backbone = models.backbone(args.backbone, preprocess_mode=args.preprocess_mode)

    #print("backbone")
    #print('='*30)
    #print(backbone.retinanet.summary())
    # make sure keras is the minimum required version
    check_keras_version()

    # optionally choose specific GPU
    if args.gpu:
        os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
    keras.backend.tensorflow_backend.set_session(get_session())

    # create the generators
    train_generator, validation_generator = create_generators(args, backbone.preprocess_image)

    # create the model
    if args.snapshot is not None:
        print('Loading model, this may take a second...')
        model            = models.load_model(args.snapshot, backbone_name=args.backbone)
        training_model   = model
        prediction_model = retinanet_bbox(model=model)
    else:
        weights = args.weights
        # default to imagenet if nothing else is specified
        if weights is None and args.imagenet_weights:
            weights = backbone.download_imagenet()

        print('Creating model, this may take a second...')
        model, training_model, prediction_model = create_models(
            backbone_retinanet=backbone.retinanet,
            num_classes=train_generator.num_classes(),
            weights=weights,
            multi_gpu=args.multi_gpu,
            freeze_backbone=args.freeze_backbone,
            lr=args.lr,
            alpha=args.loss_alpha, gamma=args.loss_gamma,
            score_threshold       = args.score_threshold,
            max_detections        = args.max_detections,
            nms_threshold         = args.nms_threshold,
            submodels             = args.submodels,
            share_rpn             = args.share_rpn,
            class_feature_sizes   = args.class_feature_sizes,
            regr_feature_sizes    = args.regr_feature_sizes,
            common_feature_sizes  = args.common_feature_sizes,
            coordconv             = args.coordconv,
        )

    # print model summary
    print(model.summary())

    # this lets the generator compute backbone layer shapes using the actual backbone model
    if 'vgg' in args.backbone or 'densenet' in args.backbone:
        train_generator.compute_shapes = make_shapes_callback(model)
        if validation_generator:
            validation_generator.compute_shapes = train_generator.compute_shapes

    # create the callbacks
    callbacks = create_callbacks(
        model,
        training_model,
        prediction_model,
        validation_generator,
        args,
        lr_patience=args.lr_patience,
        lr_drop_factor=args.lr_drop_factor,
    )

    # start training
    homogenous_augm_wrapper = create_homogenous_augm_wrapper(args)
    training_model.fit_generator(
        generator=homogenous_augm_wrapper(train_generator),
        steps_per_epoch=args.steps,
        validation_data=validation_generator,
        validation_steps=len(validation_generator),
        epochs=args.epochs,
        verbose=1,
        callbacks=callbacks,
    )


if __name__ == '__main__':
    main()
