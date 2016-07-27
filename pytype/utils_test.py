"""Tests for utils.py."""

import itertools
import os


from pytype import utils
from pytype.pytd import cfg as typegraph
from pytype.pytd import pytd
from pytype.tests import test_inference

import unittest

# pylint: disable=invalid-name


class DummyValue(object):
  """A class with a 'parameters' function, for testing cartesian products."""

  def __init__(self, index):
    self.index = index
    self._parameters = []

  def set_parameters(self, parameters):
    self._parameters = parameters

  def unique_parameter_values(self):
    return [param.bindings for param in self._parameters]

  def __repr__(self):
    return "x%d" % self.index


class Node(object):
  """A graph node, for testing topological sorting."""

  def __init__(self, name, *incoming):
    self.name = name
    self.incoming = incoming

  def __repr__(self):
    return "Node(%s)" % self.name


class UtilsTest(unittest.TestCase):

  def setUp(self):
    self.prog = typegraph.Program()
    self.current_location = self.prog.NewCFGNode()

  def testReplaceExtension(self):
    self.assertEquals("foo.bar", utils.replace_extension("foo.txt", "bar"))
    self.assertEquals("foo.bar", utils.replace_extension("foo.txt", ".bar"))
    self.assertEquals("a.b.c.bar", utils.replace_extension("a.b.c.txt", ".bar"))
    self.assertEquals("a.b/c.bar", utils.replace_extension("a.b/c.d", ".bar"))
    self.assertEquals("xyz.bar", utils.replace_extension("xyz", "bar"))

  def testVariableProduct(self):
    u1 = self.prog.NewVariable("u1", [1, 2], [], self.current_location)
    u2 = self.prog.NewVariable("u2", [3, 4], [], self.current_location)
    product = utils.variable_product([u1, u2])
    pairs = [[a.data for a in d]
             for d in product]
    self.assertItemsEqual(pairs, [
        [1, 3],
        [1, 4],
        [2, 3],
        [2, 4],
    ])

  def testDeepVariableProduct(self):
    x1, x2, x3, x4, x5, x6 = [DummyValue(i + 1) for i in range(6)]
    v1 = self.prog.NewVariable("v1", [x1, x2], [], self.current_location)
    v2 = self.prog.NewVariable("v2", [x3], [], self.current_location)
    v3 = self.prog.NewVariable("v3", [x4, x5], [], self.current_location)
    v4 = self.prog.NewVariable("v4", [x6], [], self.current_location)
    x1.set_parameters([v2, v3])
    product = utils.deep_variable_product([v1, v4])
    rows = [{a.data for a in row}
            for row in product]
    self.assertItemsEqual(rows, [
        {x1, x3, x4, x6},
        {x1, x3, x5, x6},
        {x2, x6},
    ])

  def testDeepVariableProductWithEmptyVariables(self):
    x1 = DummyValue(1)
    v1 = self.prog.NewVariable("v1", [x1], [], self.current_location)
    v2 = self.prog.NewVariable("v2", [], [], self.current_location)
    x1.set_parameters([v2])
    product = utils.deep_variable_product([v1])
    rows = [{a.data for a in row}
            for row in product]
    self.assertItemsEqual(rows, [{x1}])

  def testDeepVariableProductWithEmptyTopLayer(self):
    x1 = DummyValue(1)
    v1 = self.prog.NewVariable("v1", [x1], [], self.current_location)
    v2 = self.prog.NewVariable("v2", [], [], self.current_location)
    product = utils.deep_variable_product([v1, v2])
    rows = [{a.data for a in row}
            for row in product]
    self.assertItemsEqual(rows, [{x1}])

  def testDeepVariableProductWithCycle(self):
    x1, x2, x3, x4, x5, x6 = [DummyValue(i + 1) for i in range(6)]
    v1 = self.prog.NewVariable("v1", [x1, x2], [], self.current_location)
    v2 = self.prog.NewVariable("v2", [x3], [], self.current_location)
    v3 = self.prog.NewVariable("v3", [x4, x5], [], self.current_location)
    v4 = self.prog.NewVariable("v4", [x6], [], self.current_location)
    x1.set_parameters([v2, v3])
    x5.set_parameters([v1])
    product = utils.deep_variable_product([v1, v4])
    rows = [{a.data for a in row}
            for row in product]
    self.assertItemsEqual(rows, [
        {x1, x3, x4, x6},
        {x1, x2, x3, x5, x6},
        {x1, x3, x5, x6},
        {x2, x6},
    ])

  def testVariableProductDict(self):
    u1 = self.prog.NewVariable("u1", [1, 2], [], self.current_location)
    u2 = self.prog.NewVariable("u2", [3, 4], [], self.current_location)
    product = utils.variable_product_dict({"a": u1, "b": u2})
    pairs = [{k: a.data for k, a in d.iteritems()}
             for d in product]
    self.assertItemsEqual(pairs, [
        {"a": 1, "b": 3},
        {"a": 1, "b": 4},
        {"a": 2, "b": 3},
        {"a": 2, "b": 4},
    ])

  def testNumericSortKey(self):
    k = utils.numeric_sort_key
    self.assertLess(k("1aaa"), k("12aa"))
    self.assertLess(k("12aa"), k("123a"))
    self.assertLess(k("a1aa"), k("a12a"))
    self.assertLess(k("a12a"), k("a123"))

  def testPrettyDNF(self):
    dnf = [["a", "b"], "c", ["d", "e", "f"]]
    self.assertEquals(utils.pretty_dnf(dnf), "(a & b) | c | (d & e & f)")

  def testComputePredecessors(self):
    # n7      n6
    #  ^      ^
    #  |      |
    #  |      |
    # n1 ---> n20 --> n3 --> n5 -+
    #         | ^            ^   |
    #         | |            |   |
    #         | +------------|---+
    #         v              |
    #         n4 ------------+
    n1 = self.prog.NewCFGNode("n1")
    n20 = n1.ConnectNew("n20")
    n3 = n20.ConnectNew("n3")
    n4 = n20.ConnectNew("n4")
    n5 = n3.ConnectNew("n5")
    n6 = n20.ConnectNew("n6")
    n7 = n1.ConnectNew("n7")
    n3.ConnectTo(n5)
    n4.ConnectTo(n5)
    n5.ConnectTo(n20)

    nodes = [n1, n20, n3, n4, n5, n6, n7]
    r = utils.compute_predecessors(nodes)
    self.assertItemsEqual(r[n1], {n1})
    self.assertItemsEqual(r[n20], {n1, n20, n3, n4, n5})
    self.assertItemsEqual(r[n3], {n1, n20, n3, n4, n5})
    self.assertItemsEqual(r[n4], {n1, n20, n3, n4, n5})
    self.assertItemsEqual(r[n5], {n1, n20, n3, n4, n5})
    self.assertItemsEqual(r[n6], {n1, n20, n3, n4, n5, n6})
    self.assertItemsEqual(r[n7], {n1, n7})

  def testOrderNodes0(self):
    order = utils.order_nodes([])
    self.assertItemsEqual(order, [])

  def testOrderNodes1(self):
    # n1 --> n2
    n1 = self.prog.NewCFGNode("n1")
    n2 = n1.ConnectNew("n2")
    order = utils.order_nodes([n1, n2])
    self.assertItemsEqual([n1, n2], order)

  def testOrderNodes2(self):
    # n1   n2(dead)
    n1 = self.prog.NewCFGNode("n1")
    n2 = self.prog.NewCFGNode("n2")
    order = utils.order_nodes([n1, n2])
    self.assertItemsEqual([n1], order)

  def testOrderNodes3(self):
    # n1 --> n2 --> n3
    # ^             |
    # +-------------+
    n1 = self.prog.NewCFGNode("n1")
    n2 = n1.ConnectNew("n2")
    n3 = n2.ConnectNew("n3")
    n3.ConnectTo(n1)
    order = utils.order_nodes([n1, n2, n3])
    self.assertItemsEqual([n1, n2, n3], order)

  def testOrderNodes4(self):
    # n1 --> n3 --> n2
    # ^      |
    # +------+
    n1 = self.prog.NewCFGNode("n1")
    n3 = n1.ConnectNew("n3")
    n2 = n3.ConnectNew("n2")
    n3.ConnectTo(n1)
    order = utils.order_nodes([n1, n2, n3])
    self.assertItemsEqual([n1, n3, n2], order)

  def testOrderNodes5(self):
    # n1 --> n3 --> n2
    # ^      |
    # +------+      n4(dead)
    n1 = self.prog.NewCFGNode("n1")
    n3 = n1.ConnectNew("n3")
    n2 = n3.ConnectNew("n2")
    n3.ConnectTo(n1)
    n4 = self.prog.NewCFGNode("n4")
    order = utils.order_nodes([n1, n2, n3, n4])
    self.assertItemsEqual([n1, n3, n2], order)

  def testOrderNodes6(self):
    #  +-------------------+
    #  |                   v
    # n1 --> n2 --> n3 --> n5
    #        ^      |
    #        +------n4
    n1 = self.prog.NewCFGNode("n1")
    n2 = n1.ConnectNew("n2")
    n3 = n2.ConnectNew("n3")
    n4 = n3.ConnectNew("n4")
    n4.ConnectTo(n2)
    n5 = n3.ConnectNew("n5")
    n1.ConnectTo(n5)
    order = utils.order_nodes([n1, n5, n4, n3, n2])
    self.assertItemsEqual([n1, n2, n3, n4, n5], order)

  def testOrderNodes7(self):
    #  +---------------------------------+
    #  |                                 v
    # n1 --> n2 --> n3 --> n4 --> n5 --> n6
    #        ^      |      ^      |
    #        |      v      |      v
    #        +------n7     +------n8
    n1 = self.prog.NewCFGNode("n1")
    n2 = n1.ConnectNew("n2")
    n3 = n2.ConnectNew("n3")
    n4 = n3.ConnectNew("n4")
    n5 = n4.ConnectNew("n5")
    n6 = n5.ConnectNew("n6")
    n7 = n3.ConnectNew("n7")
    n7.ConnectTo(n2)
    n8 = n5.ConnectNew("n8")
    n8.ConnectTo(n4)
    n1.ConnectTo(n6)
    order = utils.order_nodes([n1, n2, n3, n4, n5, n6, n7, n8])
    self.assertItemsEqual([n1, n2, n3, n7, n4, n5, n8, n6], order)

  def testTopologicalSort(self):
    n1 = Node("1")
    n2 = Node("2", n1)
    n3 = Node("3", n2)
    n4 = Node("4", n2, n3)
    for permutation in itertools.permutations([n1, n2, n3, n4]):
      self.assertEquals(list(utils.topological_sort(permutation)),
                        [n1, n2, n3, n4])

  def testTopologicalSort2(self):
    n1 = Node("1")
    n2 = Node("2", n1)
    self.assertEquals(list(utils.topological_sort([n1, n2, 3, 4]))[-1], n2)

  def testTopologicalSortCycle(self):
    n1 = Node("1")
    n2 = Node("2")
    n1.incoming = [n2]
    n2.incoming = [n1]
    generator = utils.topological_sort([n1, n2])
    self.assertRaises(ValueError, list, generator)

  def testTopologicalSortSubCycle(self):
    n1 = Node("1")
    n2 = Node("2")
    n3 = Node("3")
    n1.incoming = [n2]
    n2.incoming = [n1]
    n3.incoming = [n1, n2]
    generator = utils.topological_sort([n1, n2, n3])
    self.assertRaises(ValueError, list, generator)

  def testTopologicalSortGetattr(self):
    self.assertEquals(list(utils.topological_sort([1])), [1])

  def testFlattenSuperclasses(self):
    cls_a = pytd.Class("A", (), (), (), ())
    cls_b = pytd.Class("B", (cls_a,), (), (), ())
    cls_c = pytd.Class("C", (cls_a,), (), (), ())
    cls_d = pytd.Class("D", (cls_c,), (), (), ())
    cls_e = pytd.Class("E", (cls_d, cls_b), (), (), ())
    self.assertItemsEqual(utils.flattened_superclasses(cls_e),
                          [cls_a, cls_b, cls_c, cls_d, cls_e])

  def testTempdir(self):
    with utils.Tempdir() as d:
      filename1 = d.create_file("foo.txt")
      filename2 = d.create_file("bar.txt", "\tdata2")
      filename3 = d.create_file("baz.txt", "data3")
      filename4 = d.create_file("d1/d2/qqsv.txt", "  data4.1\n  data4.2")
      filename5 = d.create_directory("directory")
      self.assertEquals(filename1, d["foo.txt"])
      self.assertEquals(filename2, d["bar.txt"])
      self.assertEquals(filename3, d["baz.txt"])
      self.assertEquals(filename4, d["d1/d2/qqsv.txt"])
      self.assertTrue(os.path.isdir(d.path))
      self.assertTrue(os.path.isfile(filename1))
      self.assertTrue(os.path.isfile(filename2))
      self.assertTrue(os.path.isfile(filename3))
      self.assertTrue(os.path.isfile(filename4))
      self.assertTrue(os.path.isdir(os.path.join(d.path, "d1")))
      self.assertTrue(os.path.isdir(os.path.join(d.path, "d1", "d2")))
      self.assertTrue(os.path.isdir(filename5))
      self.assertEqual(filename4, os.path.join(d.path, "d1", "d2", "qqsv.txt"))
      for filename, contents in [(filename1, ""),
                                 (filename2, "data2"),  # dedented
                                 (filename3, "data3"),
                                 (filename4, "data4.1\ndata4.2"),  # dedented
                                ]:
        with open(filename, "rb") as fi:
          self.assertEquals(fi.read(), contents)
    self.assertFalse(os.path.isdir(d.path))
    self.assertFalse(os.path.isfile(filename1))
    self.assertFalse(os.path.isfile(filename2))
    self.assertFalse(os.path.isfile(filename3))
    self.assertFalse(os.path.isdir(os.path.join(d.path, "d1")))
    self.assertFalse(os.path.isdir(os.path.join(d.path, "d1", "d2")))
    self.assertFalse(os.path.isdir(filename5))

  def testListStripPrefix(self):
    self.assertEqual([1, 2, 3], utils.list_strip_prefix([1, 2, 3], []))
    self.assertEqual([2, 3], utils.list_strip_prefix([1, 2, 3], [1]))
    self.assertEqual([3], utils.list_strip_prefix([1, 2, 3], [1, 2]))
    self.assertEqual([], utils.list_strip_prefix([1, 2, 3], [1, 2, 3]))
    self.assertEqual([1, 2, 3],
                     utils.list_strip_prefix([1, 2, 3], [0, 1, 2, 3]))
    self.assertEqual([], utils.list_strip_prefix([], [1, 2, 3]))
    self.assertEqual(list("wellington"), utils.list_strip_prefix(
        list("newwellington"), list("new")))
    self.assertEqual(
        "a.somewhat.long.path.src2.d3.shrdlu".split("."),
        utils.list_strip_prefix(
            "top.a.somewhat.long.path.src2.d3.shrdlu".split("."),
            "top".split(".")))

  def testListStartsWith(self):
    self.assertTrue(utils.list_startswith([1, 2, 3], []))
    self.assertTrue(utils.list_startswith([1, 2, 3], [1]))
    self.assertTrue(utils.list_startswith([1, 2, 3], [1, 2]))
    self.assertTrue(utils.list_startswith([1, 2, 3], [1, 2, 3]))
    self.assertFalse(utils.list_startswith([1, 2, 3], [2]))
    self.assertTrue(utils.list_startswith([], []))
    self.assertFalse(utils.list_startswith([], [1]))

  @utils.memoize
  def _f1(self, x, y):
    return x + y

  def testMemoize1(self):
    l1 = self._f1((1,), (2,))
    l2 = self._f1(x=(1,), y=(2,))
    l3 = self._f1((1,), y=(2,))
    self.assertIs(l1, l2)
    self.assertIs(l2, l3)
    l1 = self._f1((1,), (2,))
    l2 = self._f1((1,), (3,))
    self.assertIsNot(l1, l2)

  @utils.memoize("x")
  def _f2(self, x, y):
    return x + y

  def testMemoize2(self):
    l1 = self._f2((1,), (2,))
    l2 = self._f2((1,), (3,))
    self.assertIs(l1, l2)
    l1 = self._f2(x=(1,), y=(2,))
    l2 = self._f2(x=(1,), y=(3,))
    self.assertIs(l1, l2)
    l1 = self._f2((1,), (2,))
    l2 = self._f2((2,), (2,))
    self.assertIsNot(l1, l2)

  @utils.memoize("(x, id(y))")
  def _f3(self, x, y):
    return x + y

  def testMemoize3(self):
    l1 = self._f3((1,), (2,))
    l2 = self._f3((1,), (2,))
    self.assertIsNot(l1, l2)  # two different ids
    y = (2,)
    l1 = self._f3((1,), y)
    l2 = self._f3((1,), y)
    l3 = self._f3(x=(1,), y=y)
    self.assertIs(l1, l2)
    self.assertIs(l2, l3)

  @utils.memoize("(x, y)")
  def _f4(self, x=1, y=2):
    return x + y

  def testMemoize4(self):
    z1 = self._f4(1, 2)
    z2 = self._f4(1, 3)
    self.assertNotEquals(z1, z2)
    z1 = self._f4(1, 2)
    z2 = self._f4(1, 2)
    self.assertIs(z1, z2)
    z1 = self._f4()
    z2 = self._f4()
    self.assertIs(z1, z2)
    z1 = self._f4()
    z2 = self._f4(1, 2)
    self.assertIs(z1, z2)

  def testMemoize5(self):
    class Foo(object):

      @utils.memoize("(self, x, y)")
      def _f5(self, x, y):
        return x + y
    foo1 = Foo()
    foo2 = Foo()
    z1 = foo1._f5((1,), (2,))
    z2 = foo2._f5((1,), (2,))
    z3 = foo2._f5((1,), (2,))
    self.assertFalse(z1 is z2)
    self.assertTrue(z2 is z3)

  def testMonitorDict(self):
    d = utils.MonitorDict()
    changestamp = d.changestamp
    var = self.prog.NewVariable("var")
    d["key"] = var
    self.assertGreater(d.changestamp, changestamp)
    changestamp = d.changestamp
    var.AddBinding("data")
    self.assertGreater(d.changestamp, changestamp)
    changestamp = d.changestamp
    var.AddBinding("data")  # No change because this is duplicate data
    self.assertEquals(d.changestamp, changestamp)
    changestamp = d.changestamp
    del d["key"]
    self.assertGreater(d.changestamp, changestamp)

  def testAliasingDict(self):
    # Since the aliasing dict changes the basic way a dictionary works, we
    # require every method to be overridden
    self.assertFalse(set(dict.__dict__) - set(utils.AliasingDict.__dict__))
    d = utils.AliasingDict()
    d.add_alias("alias", "name")
    self.assertNotIn("alias", d)
    self.assertNotIn("name", d)
    var1 = self.prog.NewVariable("var1")
    d["alias"] = var1
    self.assertIn("name", d)
    self.assertIn("alias", d)
    self.assertEquals(var1, d["name"])
    self.assertEquals(d["name"], d["alias"])
    self.assertEquals(d["alias"], d.get("alias"))
    self.assertEquals(d["name"], d.get("name"))
    self.assertEquals(None, d.get("other_name"))
    var2 = self.prog.NewVariable("var2")
    d["name"] = var2
    self.assertEquals(var2, d["name"])
    self.assertEquals(d["name"], d["alias"])

  def testAliasingDictRealiasing(self):
    d = utils.AliasingDict()
    d.add_alias("alias1", "name")
    d.add_alias("alias2", "name")
    self.assertRaises(AssertionError,
                      lambda: d.add_alias("name", "other_name"))
    self.assertRaises(AssertionError,
                      lambda: d.add_alias("alias1", "other_name"))
    d.add_alias("alias1", "name")
    d.add_alias("alias2", "alias1")
    d.add_alias("alias1", "alias2")
    # Check that the name, alias1, and alias2 still all refer to the same key
    var = self.prog.NewVariable("var")
    d["alias1"] = var
    self.assertEquals(1, len(d))
    self.assertEquals(var, d["name"])
    self.assertEquals(var, d["alias1"])
    self.assertEquals(var, d["alias2"])

  def testAliasingDictMatches(self):
    d = utils.AliasingDict()
    d["name1"] = None
    d["name2"] = None
    d.add_alias("alias1", "name1")
    d.add_alias("alias2", "name2")
    d.add_alias("alias3", "name2")
    self.assertTrue(d.matches({"name1": None, "name2": None}))
    self.assertTrue(d.matches({"name1": None, "alias2": None}))
    self.assertTrue(d.matches({"name1": None, "alias3": None}))
    self.assertTrue(d.matches({"alias1": None, "name2": None}))
    self.assertTrue(d.matches({"alias1": None, "alias2": None}))
    self.assertTrue(d.matches({"alias1": None, "alias3": None}))
    self.assertTrue(d.matches({"name1": None, "name2": None, "name3": None}))
    self.assertFalse(d.matches({"name1": None, "alias1": None}))
    self.assertFalse(d.matches({"alias2": None, "alias3": None}))
    self.assertFalse(d.matches({"name2": None}))
    self.assertFalse(d.matches({"name1": None, "name4": None}))

  def testAliasingDictTransitive(self):
    d = utils.AliasingDict()
    d.add_alias("alias1", "name")
    d.add_alias("alias2", "alias1")
    d["name"] = self.prog.NewVariable("var")
    self.assertEquals(1, len(d))
    self.assertEquals(d["name"], d["alias1"])
    self.assertEquals(d["alias1"], d["alias2"])

  def testDynamicVar(self):
    var = utils.DynamicVar()
    self.assertIsNone(var.get())
    with var.bind(123):
      self.assertEquals(123, var.get())
      with var.bind(456):
        self.assertEquals(456, var.get())
      self.assertEquals(123, var.get())
    self.assertIsNone(var.get())

  def testAnnotatingDecorator(self):
    foo = utils.AnnotatingDecorator()
    @foo(3)
    def f():  # pylint: disable=unused-variable
      pass
    self.assertEquals(foo.lookup["f"], 3)


if __name__ == "__main__":
  test_inference.main()
