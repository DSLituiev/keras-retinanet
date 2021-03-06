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

import keras
from .. import initializers
from .. import layers
from ..layers import coord

import numpy as np


def default_classification_model(
    num_classes,
    num_anchors,
    pyramid_feature_size=256,
    prior_probability=0.01,
    feature_sizes=[256]*4,
    name='classification_submodel'
    ):
    """ Creates the default regression submodel.

    Args
        num_classes                 : Number of classes to predict a score for at each feature level.
        num_anchors                 : Number of anchors to predict classification scores for at each feature level.
        pyramid_feature_size        : The number of filters to expect from the feature pyramid levels.
        classification_feature_size : The number of filters to use in the layers in the classification submodel.
        name                        : The name of the submodel.

    Returns
        A keras.models.Model that predicts classes for each anchor.
    """
    options = {
        'kernel_size' : 3,
        'strides'     : 1,
        'padding'     : 'same',
    }

    if keras.backend.image_data_format() == 'channels_first':
        inputs  = keras.layers.Input(shape=(pyramid_feature_size, None, None))
    else:
        inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
    outputs = inputs
    for i,fs in enumerate(feature_sizes):
        outputs = keras.layers.Conv2D(
            filters=fs,
            activation='relu',
            name='pyramid_classification_{}'.format(i),
            kernel_initializer=keras.initializers.normal(mean=0.0, stddev=0.01, seed=None),
            bias_initializer='zeros',
            **options
        )(outputs)

    outputs = keras.layers.Conv2D(
        filters=num_classes * num_anchors,
        kernel_initializer=keras.initializers.zeros(),
        bias_initializer=initializers.PriorProbability(probability=prior_probability),
        name='pyramid_classification',
        **options
    )(outputs)

    # reshape output and apply sigmoid
    if keras.backend.image_data_format() == 'channels_first':
        outputs = keras.layers.Permute((2, 3, 1), name='pyramid_classification_permute')(outputs)
    outputs = keras.layers.Reshape((-1, num_classes), name='pyramid_classification_reshape')(outputs)
    outputs = keras.layers.Activation('sigmoid', name='pyramid_classification_sigmoid')(outputs)

    return keras.models.Model(inputs=inputs, outputs=outputs, name=name)


def default_regression_model(num_anchors, pyramid_feature_size=256,
                             feature_sizes=[256]*4, name='regression_submodel'):
    """ Creates the default regression submodel.

    Args
        num_anchors             : Number of anchors to regress for each feature level.
        pyramid_feature_size    : The number of filters to expect from the feature pyramid levels.
        regression_feature_size : The number of filters to use in the layers in the regression submodel.
        name                    : The name of the submodel.

    Returns
        A keras.models.Model that predicts regression values for each anchor.
    """
    # All new conv layers except the final one in the
    # RetinaNet (classification) subnets are initialized
    # with bias b = 0 and a Gaussian weight fill with stddev = 0.01.
    options = {
        'kernel_size'        : 3,
        'strides'            : 1,
        'padding'            : 'same',
        'kernel_initializer' : keras.initializers.normal(mean=0.0, stddev=0.01, seed=None),
        'bias_initializer'   : 'zeros'
    }

    if keras.backend.image_data_format() == 'channels_first':
        inputs  = keras.layers.Input(shape=(pyramid_feature_size, None, None))
    else:
        inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
    outputs = inputs
    for i,fs in enumerate(feature_sizes):
        outputs = keras.layers.Conv2D(
            filters=fs,
            activation='relu',
            name='pyramid_regression_{}'.format(i),
            **options
        )(outputs)

    outputs = keras.layers.Conv2D(num_anchors * 4, name='pyramid_regression', **options)(outputs)
    if keras.backend.image_data_format() == 'channels_first':
        outputs = keras.layers.Permute((2, 3, 1), name='pyramid_regression_permute')(outputs)
    outputs = keras.layers.Reshape((-1, 4), name='pyramid_regression_reshape')(outputs)

    return keras.models.Model(inputs=inputs, outputs=outputs, name=name)


def CommonPFModel(num_anchors, pyramid_feature_size=256,
                 feature_sizes=[256]*2, 
                 name='common_submodel',
                 activation='relu',
                 coordconv = False,
                 ):
        """ Creates the default joint submodel.

        Args
            num_anchors             : Number of anchors to regress for each feature level.
            pyramid_feature_size    : The number of filters to expect from the feature pyramid levels.
            regression_feature_size : The number of filters to use in the layers in the regression submodel.
            name                    : The name of the submodel.

        Returns
            A keras.models.Model that predicts regression values for each anchor.
        """
        if coordconv:
            print("USING COORDCONV")
        # All new conv layers except the final one in the
        # RetinaNet (classification) subnets are initialized
        # with bias b = 0 and a Gaussian weight fill with stddev = 0.01.
        options = {
            'kernel_size'        : 3,
            'strides'            : 1,
            'padding'            : 'same',
            'kernel_initializer' : keras.initializers.normal(mean=0.0, stddev=0.01, seed=None),
            'bias_initializer'   : 'zeros'
        }

        inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
        outputs = inputs

        conv2d = keras.layers.Conv2D
        if coordconv:
            outputs = coord.CoordinateChannel2D()(inputs)
        for i,fs in enumerate(feature_sizes):
            outputs = conv2d(
                filters=fs,
                activation=activation,
                name='pyramid_joint_{}'.format(i),
                **options
            )(outputs)

        return keras.Model(inputs=inputs, outputs=outputs, name=name)


def RegrModel(num_anchors, pyramid_feature_size=256,
                 feature_sizes=[256]*2, 
                 name='regression_submodel',
                 coordconv=False,
                 activation='relu'):
    """ Creates the default regression submodel.

    Args
        num_anchors             : Number of anchors to regress for each feature level.
        pyramid_feature_size    : The number of filters to expect from the feature pyramid levels.
        regression_feature_size : The number of filters to use in the layers in the regression submodel.
        name                    : The name of the submodel.

    Returns
        A keras.models.Model that predicts regression values for each anchor.
    """
    # All new conv layers except the final one in the
    # RetinaNet (classification) subnets are initialized
    # with bias b = 0 and a Gaussian weight fill with stddev = 0.01.
    options = {
        'kernel_size'        : 3,
        'strides'            : 1,
        'padding'            : 'same',
        'kernel_initializer' : keras.initializers.normal(mean=0.0, stddev=0.01, seed=None),
        'bias_initializer'   : 'zeros'
    }

    inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
    outputs = inputs

    conv2d = keras.layers.Conv2D
    if coordconv:
        outputs = coord.CoordinateChannel2D()(inputs)
    for i,fs in enumerate(feature_sizes):
        outputs = conv2d(
            filters=fs,
            activation=activation,
            name='pyramid_regression_{}'.format(i),
            **options
        )(outputs)

    outputs = keras.layers.Conv2D(num_anchors * 4, name='pyramid_regression', **options)(outputs)
    outputs = keras.layers.Reshape((-1, 4), name='pyramid_regression_reshape')(outputs)
    return keras.Model(inputs=inputs, outputs=outputs, name=name)


def ClassModel(
                num_classes,
                num_anchors,
                pyramid_feature_size=256,
                prior_probability=0.01,
                feature_sizes=[256]*2, 
                name='classification_submodel',
                activation='relu',
                final_activation=True,
                coordconv=False,
                ):

    """ Creates the default regression submodel.

    Args
        num_classes                 : Number of classes to predict a score for at each feature level.
        num_anchors                 : Number of anchors to predict classification scores for at each feature level.
        pyramid_feature_size        : The number of filters to expect from the feature pyramid levels.
        classification_feature_size : The number of filters to use in the layers in the classification submodel.
        name                        : The name of the submodel.

    Returns
        A keras.models.Model that predicts classes for each anchor.
    """
    options = {
        'kernel_size' : 3,
        'strides'     : 1,
        'padding'     : 'same',
    }

    inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
    outputs = inputs

    conv2d = keras.layers.Conv2D
    if coordconv:
        outputs = coord.CoordinateChannel2D()(inputs)
    for i,fs in enumerate(feature_sizes):
        outputs = conv2d(
                        filters=fs,
                        activation=activation,
                        name='pyramid_classification_{}'.format(i),
                        kernel_initializer=keras.initializers.normal(mean=0.0, stddev=0.01, seed=None),
                        bias_initializer='zeros',
                        **options
                        )(outputs)

    outputs = keras.layers.Conv2D(
        filters=num_classes * num_anchors,
        kernel_initializer=keras.initializers.zeros(),
        bias_initializer=initializers.PriorProbability(probability=prior_probability),
        name='pyramid_classification',
        **options
        )(outputs)
    # reshape output and apply sigmoid
    outputs = keras.layers.Reshape((-1, num_classes),
                                   name='pyramid_classification_reshape')(outputs)
    if final_activation:
        outputs = keras.layers.Activation('sigmoid', name='pyramid_classification_sigmoid')(outputs)
    return keras.Model(inputs, outputs, name=name)
    


class AnchorParameters:
    """ The parameteres that define how anchors are generated.

    Args
        sizes   : List of sizes to use. Each size corresponds to one feature level.
        strides : List of strides to use. Each stride correspond to one feature level.
        ratios  : List of ratios to use per location in a feature map.
        scales  : List of scales to use per location in a feature map.
    """
    def __init__(self, sizes, strides, ratios, scales):
        self.sizes   = sizes
        self.strides = strides
        self.ratios  = ratios
        self.scales  = scales

    def num_anchors(self):
        return len(self.ratios) * len(self.scales)


"""
The default anchor parameters.
"""
AnchorParameters.default = AnchorParameters(
    sizes   = [32, 64, 128, 256, 512],
    strides = [8, 16, 32, 64, 128],
    ratios  = np.array([0.5, 1, 2], keras.backend.floatx()),
    scales  = np.array([2 ** 0, 2 ** (1.0 / 3.0), 2 ** (2.0 / 3.0)], keras.backend.floatx()),
)



def joint_submodels(num_classes, num_anchors,
                    pyramid_feature_size=256,
                    common_feature_sizes=[256,256],
                    class_feature_sizes=[256,256],
                    regr_feature_sizes=[256,256],
                    coordconv=False,
                    ):
    """ Create a list of default submodels used for object detection.

    The default submodels contains a regression submodel and a classification submodel.

    Args
        num_classes : Number of classes to use.
        num_anchors : Number of base anchors.

    Returns
        A list of tuple, where the first element is the name of the submodel and the second element is the submodel itself.
    """

    inputs  = keras.layers.Input(shape=(None, None, pyramid_feature_size))
    common_out = CommonPFModel(num_classes, feature_sizes=common_feature_sizes,
                               coordconv=coordconv,
                              )(inputs)
    regr_out   = RegrModel(num_anchors, feature_sizes=regr_feature_sizes,
                           pyramid_feature_size=common_feature_sizes[-1],
                           coordconv=False,
                           )(common_out)

    class_out = ClassModel(num_classes, num_anchors,
                           feature_sizes=class_feature_sizes,
                           pyramid_feature_size=common_feature_sizes[-1],
                           coordconv=False,
                           final_activation=True)(common_out)

    return [
        ('regression',     keras.Model(inputs=inputs, outputs=regr_out, name='regr_model')),
        ('classification', keras.Model(inputs=inputs, outputs=class_out, name='class_model'))
    ]


def default_submodels(num_classes, num_anchors,
                     class_feature_sizes=[256]*4,
                     regr_feature_sizes=[256]*4):
    """ Create a list of default submodels used for object detection.

    The default submodels contains a regression submodel and a classification submodel.

    Args
        num_classes : Number of classes to use.
        num_anchors : Number of base anchors.

    Returns
        A list of tuple, where the first element is the name of the submodel and the second element is the submodel itself.
    """
    return [
        ('regression', default_regression_model(num_anchors,
                            feature_sizes=regr_feature_sizes)),
        ('classification', default_classification_model(num_classes, num_anchors,
                            feature_sizes=class_feature_sizes))
    ]


def __build_model_pyramid(name, model, features, share=True):
    """ Applies a single submodel to each FPN level.

    Args
        name     : Name of the submodel.
        model    : The submodel to evaluate.
        features : The FPN features.
        share    : share weights between pyramid levels

    Returns
        A tensor containing the response from the submodel on the FPN features.
    """
    if share:
        return keras.layers.Concatenate(axis=1, name=name)([model(f) for f in features])
    else:
        inputs = []
        new = True
        for f in features:
            mo = model if new else keras.models.clone_model(model)
            inputs.append(mo(f))
        return keras.layers.Concatenate(axis=1, name=name)(inputs)


def _build_pyramid(models, features, share=True):
    """ Applies all submodels to each FPN level.

    Args
        models   : List of sumodels to run on each pyramid level (by default only regression, classifcation).
        features : The FPN features.

    Returns
        A list of tensors, one for each submodel.
    """
    return [__build_model_pyramid(n, m, features, share=share) for n, m in models]


def __build_anchors(anchor_parameters, features):
    """ Builds anchors for the shape of the features from FPN.

    Args
        anchor_parameters : Parameteres that determine how anchors are generated.
        features          : The FPN features.

    Returns
        A tensor containing the anchors for the FPN features.

        The shape is:
        ```
        (batch_size, num_anchors, 4)
        ```
    """
    anchors = [
        layers.Anchors(
            size=anchor_parameters.sizes[i],
            stride=anchor_parameters.strides[i],
            ratios=anchor_parameters.ratios,
            scales=anchor_parameters.scales,
            name='anchors_{}'.format(i)
        )(f) for i, f in enumerate(features)
    ]

    return keras.layers.Concatenate(axis=1, name='anchors')(anchors)


def RetinaNet(
        inputs,
        backbone_layers,
        num_classes,
        num_anchors             = 9,
        create_pyramid_features = None,
        submodels               = None,
        name                    = 'retinanet',
        share_rpn               = True,
        class_feature_sizes=[256]*4,
        regr_feature_sizes=[256]*4,
        common_feature_sizes=[256]*4,
        coordconv=False,
    ):
        """ Construct a RetinaNet model on top of a backbone.

        This model is the minimum model necessary for training (with the unfortunate exception of anchors as output).

        Args
            inputs                  : keras.layers.Input (or list of) for the input to the model.
            num_classes             : Number of classes to classify.
            num_anchors             : Number of base anchors.
            create_pyramid_features : Functor for creating pyramid features given the features C3, C4, C5 from the backbone.
            submodels               : Submodels to run on each feature map (default is regression and classification submodels).
            name                    : Name of the model.

        Returns
            A keras.models.Model which takes an image as input and outputs generated anchors and the result from each submodel on every pyramid level.

            The order of the outputs is as defined in submodels:
            ```
            [
                regression, classification, other[0], other[1], ...
            ]
            ```
        """
        if submodels is None:
            submodels = default_submodels(num_classes, num_anchors,
                                          class_feature_sizes=class_feature_sizes,
                                          regr_feature_sizes=regr_feature_sizes)
        elif submodels.startswith('joint'):
            submodels = joint_submodels(num_classes, num_anchors,
                                        class_feature_sizes=class_feature_sizes,
                                        regr_feature_sizes=regr_feature_sizes,
                                        common_feature_sizes=common_feature_sizes,
                                        coordconv=coordconv,
                                        )

        C3, C4, C5 = backbone_layers

        # compute pyramid features as per https://arxiv.org/abs/1708.02002
        if create_pyramid_features is None:
            create_pyramid_features = _create_pyramid_features
        features = create_pyramid_features(C3, C4, C5)

        # for all pyramid levels, run available submodels
        pyramids = _build_pyramid(submodels, features, share=share_rpn)
        #super(RetinaNet, self).__init__(inputs=inputs, outputs=pyramids, name=name)
        return keras.models.Model(inputs=inputs, outputs=pyramids, name=name)

retinanet = RetinaNet

def _create_pyramid_features(C3, C4, C5, feature_size=256):
    """ Creates the FPN layers on top of the backbone features.

    Args
        C3           : Feature stage C3 from the backbone.
        C4           : Feature stage C4 from the backbone.
        C5           : Feature stage C5 from the backbone.
        feature_size : The feature size to use for the resulting feature levels.

    Returns
        A list of feature levels [P3, P4, P5, P6, P7].
    """
    # upsample C5 to get P5 from the FPN paper
    P5           = keras.layers.Conv2D(feature_size, kernel_size=1, strides=1, padding='same', name='C5_reduced')(C5)
    P5_upsampled = layers.UpsampleLike(name='P5_upsampled')([P5, C4])
    P5           = keras.layers.Conv2D(feature_size, kernel_size=3, strides=1, padding='same', name='P5')(P5)

    # add P5 elementwise to C4
    P4           = keras.layers.Conv2D(feature_size, kernel_size=1, strides=1, padding='same', name='C4_reduced')(C4)
    P4           = keras.layers.Add(name='P4_merged')([P5_upsampled, P4])
    P4_upsampled = layers.UpsampleLike(name='P4_upsampled')([P4, C3])
    P4           = keras.layers.Conv2D(feature_size, kernel_size=3, strides=1, padding='same', name='P4')(P4)

    # add P4 elementwise to C3
    P3 = keras.layers.Conv2D(feature_size, kernel_size=1, strides=1, padding='same', name='C3_reduced')(C3)
    P3 = keras.layers.Add(name='P3_merged')([P4_upsampled, P3])
    P3 = keras.layers.Conv2D(feature_size, kernel_size=3, strides=1, padding='same', name='P3')(P3)

    # "P6 is obtained via a 3x3 stride-2 conv on C5"
    P6 = keras.layers.Conv2D(feature_size, kernel_size=3, strides=2, padding='same', name='P6')(C5)

    # "P7 is computed by applying ReLU followed by a 3x3 stride-2 conv on P6"
    P7 = keras.layers.Activation('relu', name='C6_relu')(P6)
    P7 = keras.layers.Conv2D(feature_size, kernel_size=3, strides=2, padding='same', name='P7')(P7)

    return [P3, P4, P5, P6, P7]


def retinanet_bbox(
    model                 = None,
    anchor_parameters     = AnchorParameters.default,
    nms                   = True,
    class_specific_filter = True,
    name                  = 'retinanet-bbox',
    score_threshold       = 0.05,
    max_detections        = 300,
    nms_threshold         = 0.5,
    **kwargs
):
    """ Construct a RetinaNet model on top of a backbone and adds convenience functions to output boxes directly.

    This model uses the minimum retinanet model and appends a few layers to compute boxes within the graph.
    These layers include applying the regression values to the anchors and performing NMS.

    Args
        model                 : RetinaNet model to append bbox layers to. If None, it will create a RetinaNet model using **kwargs.
        anchor_parameters     : Struct containing configuration for anchor generation (sizes, strides, ratios, scales).
        nms                   : Whether to use non-maximum suppression for the filtering step.
        class_specific_filter : Whether to use class specific filtering or filter for the best scoring class only.
        name                  : Name of the model.
        *kwargs               : Additional kwargs to pass to the minimal retinanet model.

    Returns
        A keras.models.Model which takes an image as input and outputs the detections on the image.

        The order is defined as follows:
        ```
        [
            boxes, scores, labels, other[0], other[1], ...
        ]
        ```
    """
    if model is None:
        model = RetinaNet(num_anchors=anchor_parameters.num_anchors(), **kwargs)

    # compute the anchors
    features = [model.get_layer(p_name).output for p_name in ['P3', 'P4', 'P5', 'P6', 'P7']]
    anchors  = __build_anchors(anchor_parameters, features)

    # we expect the anchors, regression and classification values as first output
    regression     = model.outputs[0]
    classification = model.outputs[1]

    # "other" can be any additional output from custom submodels, by default this will be []
    other = model.outputs[2:]

    # apply predicted regression to anchors
    boxes = layers.RegressBoxes(name='boxes')([anchors, regression])
    boxes = layers.ClipBoxes(name='clipped_boxes')([model.inputs[0], boxes])

    # filter detections (apply NMS / score threshold / select top-k)
    detections = layers.FilterDetections(
        nms                   = nms,
        class_specific_filter = class_specific_filter,
        score_threshold       = score_threshold,
        max_detections        = max_detections,
        nms_threshold         = nms_threshold,
        name                  = 'filtered_detections',
    )([boxes, classification] + other)

    outputs = detections

    # construct the model
    return keras.models.Model(inputs=model.inputs, outputs=outputs, name=name)
