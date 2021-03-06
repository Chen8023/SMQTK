from __future__ import absolute_import, division, print_function

import random
import unittest

import numpy as np
import pytest
import six
from six.moves import range, zip

from smqtk.algorithms import NearestNeighborsIndex
from smqtk.algorithms.nn_index.faiss import FaissNearestNeighborsIndex
from smqtk.exceptions import ReadOnlyError
from smqtk.representation.data_element.memory_element import (
    DataMemoryElement,
)
from smqtk.representation.descriptor_element.local_elements import (
    DescriptorMemoryElement,
)
from smqtk.representation.descriptor_set.memory import MemoryDescriptorSet
from smqtk.representation.key_value.memory import MemoryKeyValueStore
from smqtk.utils.configuration import configuration_test_helper


@pytest.mark.skipif(not FaissNearestNeighborsIndex.is_usable(),
                    reason="FaissNearestNeighborsIndex does not report as "
                           "usable.")
class TestFAISSIndex (unittest.TestCase):

    RAND_SEED = 42

    def _make_inst(self, descriptor_set=None, idx2uid_kvs=None,
                   uid2idx_kvs=None, **kwargs):
        """
        Make an instance of FaissNearestNeighborsIndex
        """
        if 'random_seed' not in kwargs:
            kwargs.update(random_seed=self.RAND_SEED)
        if descriptor_set is None:
            descriptor_set = MemoryDescriptorSet()
        if idx2uid_kvs is None:
            idx2uid_kvs = MemoryKeyValueStore()
        if uid2idx_kvs is None:
            uid2idx_kvs = MemoryKeyValueStore()
        return FaissNearestNeighborsIndex(descriptor_set, idx2uid_kvs,
                                          uid2idx_kvs, **kwargs)

    def test_impl_findable(self):
        self.assertIn(FaissNearestNeighborsIndex,
                      NearestNeighborsIndex.get_impls())

    def test_configuration(self):
        ex_descr_set = MemoryDescriptorSet()
        ex_i2u_kvs = MemoryKeyValueStore()
        ex_u2i_kvs = MemoryKeyValueStore()
        ex_index_elem = DataMemoryElement()
        ex_index_param_elem = DataMemoryElement()

        i = FaissNearestNeighborsIndex(
            descriptor_set=ex_descr_set, idx2uid_kvs=ex_i2u_kvs,
            uid2idx_kvs=ex_u2i_kvs, index_element=ex_index_elem,
            index_param_element=ex_index_param_elem,
            read_only=True, factory_string=u'some fact str',
            ivf_nprobe=88, use_gpu=False, gpu_id=99, random_seed=8,
        )
        for inst in configuration_test_helper(i):
            assert isinstance(inst._descriptor_set, MemoryDescriptorSet)
            assert isinstance(inst._idx2uid_kvs, MemoryKeyValueStore)
            assert isinstance(inst._uid2idx_kvs, MemoryKeyValueStore)
            assert isinstance(inst._index_element, DataMemoryElement)
            assert isinstance(inst._index_param_element, DataMemoryElement)
            assert inst.read_only is True
            assert isinstance(inst.factory_string, six.string_types)
            assert inst.factory_string == 'some fact str'
            assert inst._ivf_nprobe == 88
            assert inst._use_gpu is False
            assert inst._gpu_id == 99
            assert inst.random_seed == 8

    def test_init_invalid_nprobe(self):
        """
        Test that the nprobe value must be a positive integer.
        """
        with pytest.raises(ValueError, match=r"ivf_nprobe must be >= 1."):
            self._make_inst(ivf_nprobe=-1)

        with pytest.raises(TypeError):
            self._make_inst(ivf_nprobe=None)

    def test_configuration_null_persistence(self):
        # Make configuration based on default
        c = FaissNearestNeighborsIndex.get_default_config()
        c['descriptor_set']['type'] = 'MemoryDescriptorSet'
        c['idx2uid_kvs']['type'] = 'MemoryKeyValueStore'
        c['uid2idx_kvs']['type'] = 'MemoryKeyValueStore'

        # # Build based on configuration
        index = FaissNearestNeighborsIndex.from_config(c)
        self.assertEqual(index.factory_string, 'IDMap,Flat')
        self.assertIsInstance(index.factory_string, six.string_types)

        # Test that constructing a new instance from ``index``'s config
        # yields an index with the same configuration (idempotent).
        index2 = FaissNearestNeighborsIndex.from_config(
            index.get_config())
        self.assertEqual(index.get_config(), index2.get_config())

    def test_build_index_read_only(self):
        v = np.zeros(5, float)
        v[0] = 1.
        d = DescriptorMemoryElement('unit', 0)
        d.set_vector(v)
        test_descriptors = [d]

        index = self._make_inst(read_only=True)
        self.assertRaises(
            ReadOnlyError,
            index.build_index, test_descriptors
        )

    def test_update_index_no_input(self):
        index = self._make_inst()
        self.assertRaises(
            ValueError,
            index.update_index, []
        )

    def test_update_index_new_index(self):
        n = 100
        dim = 8
        d_set = [DescriptorMemoryElement('test', i) for i in range(n)]
        [d.set_vector(np.random.rand(dim)) for d in d_set]

        index = self._make_inst()
        index.update_index(d_set)
        self.assertEqual(index.count(), 100)
        for d in d_set:
            self.assertIn(d, index._descriptor_set)

        # Check that NN can return stuff from the set used.
        # - nearest element to the query element when the query is in the
        #   index should be the query element.
        random.seed(self.RAND_SEED)
        for _ in range(10):
            i = random.randint(0, n-1)
            q = d_set[i]
            n_elems, n_dists = index.nn(q)
            self.assertEqual(n_elems[0], q)

    def test_update_index_additive(self):
        n1 = 100
        n2 = 10
        dim = 8
        set1 = {DescriptorMemoryElement('test', i) for i in range(n1)}
        set2 = {DescriptorMemoryElement('test', i)
                for i in range(n1, n1+n2)}
        [d.set_vector(np.random.rand(dim)) for d in (set1 | set2)]

        # Create and build initial index.
        index = self._make_inst()
        index.build_index(set1)
        self.assertEqual(index.count(), len(set1))
        for d in set1:
            self.assertIn(d, index._descriptor_set)

        # Update and check that all intended descriptors are present in
        # index.
        index.update_index(set2)
        set_all = set1 | set2
        self.assertEqual(index.count(), len(set_all))
        for d in set_all:
            self.assertIn(d, index._descriptor_set)

        # Check that NN can return something from the updated set.
        # - nearest element to the query element when the query is in the
        #   index should be the query element.
        for q in set_all:
            n_elems, n_dists = index.nn(q)
            self.assertEqual(n_elems[0], q)

    def test_persistence_with_update_index(self):
        n1 = 100
        n2 = 10
        dim = 8
        set1 = {DescriptorMemoryElement('test', i) for i in range(n1)}
        set2 = {DescriptorMemoryElement('test', i)
                for i in range(n1, n1+n2)}
        [d.set_vector(np.random.rand(dim)) for d in (set1 | set2)]

        # Create index with persistent entities
        index_element = DataMemoryElement(
            content_type='application/octet-stream')
        index_param_element = DataMemoryElement(
            content_type='text/plain')
        index = self._make_inst(
            index_element=index_element,
            index_param_element=index_param_element)
        descriptor_set = index._descriptor_set
        idx2uid_kvs = index._idx2uid_kvs
        uid2idx_kvs = index._uid2idx_kvs

        # Build initial index.
        index.build_index(set1)
        self.assertEqual(index.count(), len(set1))
        for d in set1:
            self.assertIn(d, index._descriptor_set)

        # Update and check that all intended descriptors are present in
        # index.
        index.update_index(set2)
        set_all = set1 | set2
        self.assertEqual(index.count(), len(set_all))
        for d in set_all:
            self.assertIn(d, index._descriptor_set)

        del index
        index = self._make_inst(
            descriptor_set=descriptor_set,
            idx2uid_kvs=idx2uid_kvs,
            uid2idx_kvs=uid2idx_kvs,
            index_element=index_element,
            index_param_element=index_param_element)

        # Check that NN can return something from the updated set.
        # - nearest element to the query element when the query is in the
        #   index should be the query element.
        for q in set_all:
            n_elems, n_dists = index.nn(q)
            self.assertEqual(n_elems[0], q)

    def test_remove_from_index_readonly(self):
        """
        Test that we cannot call remove when the instance is read-only.
        """
        index = self._make_inst(read_only=True)
        self.assertRaises(
            ReadOnlyError,
            index.remove_from_index, [0]
        )

    def test_remove_from_index_keyerror_empty_index(self):
        """
        Test that any key should cause a key error on an empty index.
        """
        index = self._make_inst()
        self.assertRaisesRegexp(
            KeyError, '0',
            index.remove_from_index, [0]
        )
        self.assertRaisesRegexp(
            KeyError, '0',
            index.remove_from_index, ['0']
        )
        # Only includes the first key that's erroneous in the KeyError inst
        self.assertRaisesRegexp(
            KeyError, '0',
            index.remove_from_index, [0, 'other']
        )

    def test_remove_from_index_keyerror(self):
        """
        Test that we do not impact the index by trying to remove an invalid
        key.
        """
        n = 100
        dim = 8
        dset = {DescriptorMemoryElement('test', i) for i in range(n)}
        [d.set_vector(np.random.rand(dim)) for d in dset]

        index = self._make_inst()
        index.build_index(dset)

        # Try removing 2 invalid entries
        self.assertRaises(
            KeyError,
            index.remove_from_index, [100, 'something']
        )

        # Make sure that all indexed descriptors correctly return
        # themselves from an NN call.
        for d in dset:
            self.assertEqual(index.nn(d, 1)[0][0], d)

    def test_remove_from_index(self):
        """
        Test that we can actually remove from the index.
        """
        n = 100
        dim = 8
        dset = {DescriptorMemoryElement('test', i) for i in range(n)}
        [d.set_vector(np.random.rand(dim)) for d in dset]

        index = self._make_inst()
        index.build_index(dset)

        # Try removing two valid descriptors
        uids_to_remove = [10, 98]
        index.remove_from_index(uids_to_remove)

        # Check that every other element is still in the index.
        self.assertEqual(len(index), 98)
        for d in dset:
            if d.uuid() not in uids_to_remove:
                self.assertEqual(index.nn(d, 1)[0][0], d)

        # Check that descriptors matching removed uids cannot be queried
        # out of the index.
        for d in dset:
            if d.uuid() in uids_to_remove:
                self.assertNotEqual(index.nn(d, 1)[0][0], d)

    def test_remove_then_add(self):
        """
        Test that we can remove from the index and then add to it again.
        """
        n1 = 100
        n2 = 10
        dim = 8
        set1 = [DescriptorMemoryElement('test', i) for i in range(n1)]
        set2 = [DescriptorMemoryElement('test', i)
                for i in range(n1, n1 + n2)]
        [d.set_vector(np.random.rand(dim)) for d in (set1 + set2)]
        uids_to_remove = [10, 98]

        index = self._make_inst()
        index.build_index(set1)
        index.remove_from_index(uids_to_remove)
        index.update_index(set2)

        self.assertEqual(len(index), 108)
        # Removed descriptors should not be in return queries.
        self.assertNotEqual(index.nn(set1[10], 1)[0][0], set1[10])
        self.assertNotEqual(index.nn(set1[98], 1)[0][0], set1[98])
        # Every other descriptor should be queryable
        for d in set1 + set2:
            if d.uuid() not in uids_to_remove:
                self.assertEqual(index.nn(d, 1)[0][0], d)
        self.assertEqual(index._next_index, 110)

    def test_nn_many_descriptors(self):
        np.random.seed(0)

        n = 10 ** 4
        dim = 256

        d_set = [DescriptorMemoryElement('test', i) for i in range(n)]
        [d.set_vector(np.random.rand(dim)) for d in d_set]
        q = DescriptorMemoryElement('q', -1)
        q.set_vector(np.zeros((dim,)))

        faiss_index = self._make_inst()
        faiss_index.build_index(d_set)

        nbrs, dists = faiss_index.nn(q, 10)
        self.assertEqual(len(nbrs), len(dists))
        self.assertEqual(len(nbrs), 10)

    def test_nn_non_flat_index(self):
        faiss_index = self._make_inst(factory_string='IVF256,Flat')
        self.assertEqual(faiss_index.factory_string, 'IVF256,Flat')

        np.random.seed(self.RAND_SEED)
        n = 10 ** 4
        dim = 256

        d_set = [DescriptorMemoryElement('test', i) for i in range(n)]
        [d.set_vector(np.random.rand(dim)) for d in d_set]
        q = DescriptorMemoryElement('q', -1)
        q.set_vector(np.zeros((dim,)))

        faiss_index.build_index(d_set)

        nbrs, dists = faiss_index.nn(q, 10)
        self.assertEqual(len(nbrs), len(dists))
        self.assertEqual(len(nbrs), 10)

    def test_nn_preprocess_index(self):
        faiss_index = self._make_inst(factory_string='PCAR64,IVF1,Flat')
        self.assertEqual(faiss_index.factory_string, 'PCAR64,IVF1,Flat')

        np.random.seed(self.RAND_SEED)
        n = 10 ** 4
        dim = 256

        d_set = [DescriptorMemoryElement('test', i) for i in range(n)]
        [d.set_vector(np.random.rand(dim)) for d in d_set]
        q = DescriptorMemoryElement('q', -1)
        q.set_vector(np.zeros((dim,)))

        faiss_index.build_index(d_set)

        nbrs, dists = faiss_index.nn(q, 10)
        self.assertEqual(len(nbrs), len(dists))
        self.assertEqual(len(nbrs), 10)

    def test_nn_known_descriptors_euclidean_unit(self):
        dim = 5

        ###
        # Unit vectors -- Equal distance
        #
        index = self._make_inst()
        test_descriptors = []
        for i in range(dim):
            v = np.zeros(dim, float)
            v[i] = 1.
            d = DescriptorMemoryElement('unit', i)
            d.set_vector(v)
            test_descriptors.append(d)
        index.build_index(test_descriptors)
        # query descriptor -- zero vector
        # -> all modeled descriptors should be equally distant (unit
        # corners)
        q = DescriptorMemoryElement('query', 0)
        q.set_vector(np.zeros(dim, float))
        r, dists = index.nn(q, n=dim)
        self.assertEqual(len(dists), dim)
        # All dists should be 1.0, r order doesn't matter
        for d in dists:
            self.assertEqual(d, 1.)

    def test_nn_known_descriptors_nearest(self):
        dim = 5

        ###
        # Unit vectors -- Equal distance
        #
        index = self._make_inst()
        test_descriptors = []
        vectors = np.eye(dim, dtype=np.float32)
        for i in range(dim):
            d = DescriptorMemoryElement('unit', i)
            d.set_vector(vectors[i])
            test_descriptors.append(d)
        index.build_index(test_descriptors)
        # query descriptor -- first point
        q = DescriptorMemoryElement('query', 0)
        q.set_vector(vectors[0])
        r, dists = index.nn(q)
        self.assertEqual(len(dists), 1)
        # Distance should be zero
        self.assertEqual(dists[0], 0.)
        np.testing.assert_allclose(r[0].vector(), vectors[0])

    def test_nn_known_descriptors_euclidean_ordered(self):
        index = self._make_inst()

        # make vectors to return in a known euclidean distance order
        i = 100
        test_descriptors = []
        for j in range(i):
            d = DescriptorMemoryElement('ordered', j)
            d.set_vector(np.array([j, j*2], float))
            test_descriptors.append(d)
        random.shuffle(test_descriptors)
        index.build_index(test_descriptors)

        # Since descriptors were built in increasing distance from (0,0),
        # returned descriptors for a query of [0,0] should be in index
        # order.
        q = DescriptorMemoryElement('query', 99)
        q.set_vector(np.array([0, 0], float))
        r, dists = index.nn(q, n=i)

        self.assertEqual(len(dists), i)
        for j, d, dist in zip(range(i), r, dists):
            self.assertEqual(d.uuid(), j)
            np.testing.assert_equal(d.vector(), [j, j*2])

    def test_nn_ivf_nprobe_parametrization(self):
        """
        Test that increasing the nprobe parameter affects the nn query return.
        """
        # Create descriptor elements to build index with.
        np.random.seed(0)  # for "consistent" random results.
        descr_elems = [
            DescriptorMemoryElement('test', i).set_vector(v)
            for i, v in enumerate(np.random.rand(512, 2048))
        ]

        # Build an under-populated index for the parameterized IVF nlists
        # value (256). Creating 512 (~2 per cell).
        index = self._make_inst(factory_string='IVF256,Flat')
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        assert index._faiss_index.nprobe == 1
        assert len(q_results) < 64

        # Try again on a new index but with the nprobe param set to a value
        # much higher than the faiss default (1).
        # - 48 *should* be enough cells to get to at least 64 elements assuming
        #   ~2 average elements per cell.
        index = self._make_inst(factory_string='IVF256,Flat', ivf_nprobe=48)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        assert index._faiss_index.nprobe == 48
        assert len(q_results) == 64

        # Single nesting
        index = self._make_inst(factory_string="PCAR8,IVF256,Flat",
                                ivf_nprobe=48)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        assert len(q_results) == 64

        # Double nesting
        index = self._make_inst(factory_string="PCAR8,IDMap,IVF256,Flat",
                                ivf_nprobe=48)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        assert len(q_results) == 64

        # Shouldn't do anything for non-IVF indices
        # -- IDMap,HNSW32
        index = self._make_inst(factory_string="IDMap,HNSW32",
                                ivf_nprobe=2)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        # -- PCAR8,IDMap,HNSW32
        index = self._make_inst(factory_string="PCAR8,IDMap,HNSW32",
                                ivf_nprobe=2)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
        # -- PCAR8,IDMap,Flat
        index = self._make_inst(factory_string="PCAR8,IDMap,Flat",
                                ivf_nprobe=2)
        index.build_index(descr_elems)
        q_results, q_dists = index.nn(descr_elems[0], n=64)
