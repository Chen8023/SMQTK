import csv
import collections
import json
import numpy

import six
from six.moves import zip

from smqtk.utils.cli import logging, initialize_logging
from smqtk.representation.data_set.memory_set import DataMemorySet
from smqtk.algorithms.descriptor_generator.caffe_descriptor import CaffeDescriptorGenerator
from smqtk.algorithms.classifier.index_label import IndexLabelClassifier
from smqtk.representation import ClassificationElementFactory
from smqtk.representation.classification_element.memory import MemoryClassificationElement
from smqtk.representation.data_element.file_element import DataFileElement
from smqtk.representation.descriptor_set.memory import MemoryDescriptorSet


# in-memory data-set file cache
EVAL_DATASET = "eval.dataset.pickle"

CAFFE_DEPLOY = "CHANGE_ME"
CAFFE_MODEL = "CHANGE_ME"
CAFFE_IMG_MEAN = "CHANGE_ME"
# new-line separated file of index labels.
# Line index should correspont to caffe train/test truth labels.
CAFFE_LABELS = "labels.txt"

# CSV file detailing [cluster_id, ad_id, image_sha1] relationships.
EVAL_CLUSTERS_ADS_IMAGES_CSV = "eval.CP1_clusters_ads_images.csv"
# json-lines file of clusters missing from the above file. Should be at least
# composed of: {"cluster_id": <str>, ... }
EVAL_MISSING_CLUSTERS = "eval.cluster_scores.missing_clusters.jl"

OUTPUT_DESCR_PROB_SET = "cp1_img_prob_descriptors.pickle"
OUTPUT_MAX_JL = "cp1_scores_max.jl"
OUTPUT_AVG_JL = "cp1_scores_avg.jl"


###############################################################################

# Compute classification scores
initialize_logging(logging.getLogger('smqtk'), logging.DEBUG)

eval_data_set = DataMemorySet(DataFileElement(EVAL_DATASET))
img_prob_descr_set = MemoryDescriptorSet(DataFileElement(OUTPUT_DESCR_PROB_SET))

img_prob_gen = CaffeDescriptorGenerator(DataFileElement(CAFFE_DEPLOY),
                                        DataFileElement(CAFFE_MODEL),
                                        DataFileElement(CAFFE_IMG_MEAN),
                                        'prob', batch_size=1000, use_gpu=True,
                                        load_truncated_images=True)

img_c_mem_factory = ClassificationElementFactory(
    MemoryClassificationElement, {}
)
img_prob_classifier = IndexLabelClassifier(CAFFE_LABELS)

eval_data2descr = {}
d_to_proc = set()
for data in eval_data_set:
    if not img_prob_descr_set.has_descriptor(data.uuid()):
        d_to_proc.add(data)
    else:
        eval_data2descr[data] = img_prob_descr_set[data.uuid()]
if d_to_proc:
    eval_data2descr.update(
        zip(d_to_proc, img_prob_gen.generate_elements(d_to_proc))
    )
    d_to_proc.clear()
assert len(eval_data2descr) == eval_data_set.count()

index_additions = []
for data in d_to_proc:
    index_additions.append( eval_data2descr[data] )
print("Adding %d new descriptors to prob index" % len(index_additions))
img_prob_descr_set.add_many_descriptors(index_additions)

eval_classifications = \
    img_prob_classifier.classify_elements(eval_data2descr.values(),
                                          img_c_mem_factory)

###############################################################################

# The shas that were actually computed
computed_shas = {e.uuid() for e in eval_data2descr}
len(computed_shas)

cluster2ads = collections.defaultdict(set)
cluster2shas = collections.defaultdict(set)
ad2shas = collections.defaultdict(set)
sha2ads = collections.defaultdict(set)
with open(EVAL_CLUSTERS_ADS_IMAGES_CSV) as f:
    reader = csv.reader(f)
    for i, r in enumerate(reader):
        if i == 0:
            # skip header line
            continue
        c, ad, sha = r
        if sha in computed_shas:
            cluster2ads[c].add(ad)
            cluster2shas[c].add(sha)
            ad2shas[ad].add(sha)
            sha2ads[sha].add(ad)

assert len(sha2ads) == len(computed_shas)

###############################################################################

print("Collecting scores for SHA1s")
sha2score = {}
for c in eval_classifications:
    sha2score[c.uuid] = c['positive']

print("Collecting scores for ads (MAX and AVG)")
ad2score_max = {}
ad2score_avg = {}
for ad, child_shas in six.iteritems(ad2shas):
    scores = [sha2score[sha] for sha in child_shas]
    ad2score_max[ad] = numpy.max(scores)
    ad2score_avg[ad] = numpy.average(scores)

# select cluster score from max and average of child ad scores
print("Collecting scores for ads (MAX and AVG)")
cluster2score_max = {}
cluster2score_avg = {}
for c, child_ads in six.iteritems(cluster2ads):
    cluster2score_max[c] = numpy.max(    [ad2score_max[ad] for ad in child_ads])
    cluster2score_avg[c] = numpy.average([ad2score_avg[ad] for ad in child_ads])

len(cluster2score_max)

###############################################################################
missing_clusters = \
    {json.loads(l)['cluster_id'] for l in open(EVAL_MISSING_CLUSTERS)}

cluster_id_order = sorted(set(cluster2score_avg) | missing_clusters)

with open(OUTPUT_MAX_JL, 'w') as f:
    for c in cluster_id_order:
        if c in cluster2score_max:
            f.write(json.dumps({"cluster_id": c,
                                "score": float(cluster2score_max[c])}) + '\n')
        else:
            # Due to a cluster having no child ads with imagery
            print("No childred with images for cluster '%s'" % c)
            f.write(json.dumps({"cluster_id": c, "score": 0.5}) + '\n')

with open(OUTPUT_AVG_JL, 'w') as f:
    for c in cluster_id_order:
        if c in cluster2score_avg:
            f.write(json.dumps({"cluster_id": c,
                                "score": float(cluster2score_avg[c])}) + '\n')
        else:
            # Due to a cluster having no child ads with imagery
            print("No childred with images for cluster '%s'" % c)
            f.write(json.dumps({"cluster_id": c, "score": 0.5}) + '\n')
