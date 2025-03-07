# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools as ft
from collections.abc import Callable

import equinox as eqx
import jax
import jax.core
import jax.flatten_util as jfu
import jax.lax as lax
import jax.numpy as jnp
import jax.tree_util as jtu
from jaxtyping import Array, ArrayLike, Bool, PyTree, Scalar  # pyright:ignore


def two_norm(x: PyTree) -> Scalar:
    x, _ = jfu.ravel_pytree(x)
    return jnp.array(0.0) if x.size == 0 else _two_norm(x)


@jax.custom_jvp
def _two_norm(x):
    x_sq = jnp.real(x * jnp.conj(x))
    return jnp.sqrt(jnp.sum(x_sq))


@_two_norm.defjvp
def _two_norm_jvp(x, tx):
    (x,) = x
    (tx,) = tx
    out = _two_norm(x)
    # Get zero gradient, rather than NaN gradient, in these cases
    pred = (out == 0) | jnp.isinf(out)
    numerator = jnp.where(pred, 0, jnp.dot(x, tx))
    denominator = jnp.where(pred, 1, out)
    t_out = numerator / denominator
    return out, t_out


def tree_dot(a: PyTree[Array], b: PyTree[Array]) -> Array:
    a = jtu.tree_leaves(a)
    b = jtu.tree_leaves(b)
    assert len(a) == len(b)
    return sum(
        jnp.vdot(ai, bi, precision=lax.Precision.HIGHEST)
        for ai, bi in zip(a, b)
    )


def tree_where(
    pred: Bool[ArrayLike, ""], true: PyTree[ArrayLike], false: PyTree[ArrayLike]
) -> PyTree[Array]:
    keep = lambda a, b: jnp.where(pred, a, b)
    return jtu.tree_map(keep, true, false)


def max_norm(x: PyTree) -> Scalar:
    # a standard python max will fail when jax tracers are introduced.
    return jtu.tree_reduce(
        jnp.maximum,
        [jnp.max(jnp.abs(xi)) for xi in jtu.tree_leaves(x)],
    )


def resolve_rcond(rcond, n, m, dtype):
    if rcond is None:
        return jnp.finfo(dtype).eps * max(n, m)
    else:
        return jnp.where(rcond < 0, jnp.finfo(dtype).eps, rcond)


class NoneAux(eqx.Module):
    fn: Callable

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs), None


def jacobian(fn, in_size, out_size, has_aux=False):
    # Heuristic for which is better in each case
    # These could probably be tuned a lot more.
    if (in_size < 100) or (in_size <= 1.5 * out_size):
        return jax.jacfwd(fn, has_aux=has_aux)
    else:
        return jax.jacrev(fn, has_aux=has_aux)


def _to_struct(x):
    return jax.ShapeDtypeStruct(x.shape, x.dtype) if eqx.is_array(x) else x


@ft.lru_cache(maxsize=128)
def _cached_eval_shape(leaves, treedef):
    fn, args, kwargs = jtu.tree_unflatten(treedef, leaves)
    return eqx.filter_eval_shape(fn, *args, **kwargs)


def cached_eval_shape(fn, *args, **kwargs):
    tree = jtu.tree_map(_to_struct, (fn, args, kwargs))
    leaves, treedef = jtu.tree_flatten(tree)
    leaves = tuple(leaves)
    return _cached_eval_shape(leaves, treedef)


def default_floating_dtype():
    return jnp.float64 if jax.config.jax_enable_x64 else jnp.float32


def _asarray(dtype, x):
    return jnp.asarray(x, dtype=dtype)


# Work around JAX issue #15676
_asarray = jax.custom_jvp(_asarray, nondiff_argnums=(0,))


@_asarray.defjvp
def _asarray_jvp(dtype, x, tx):
    (x,) = x
    (tx,) = tx
    return _asarray(dtype, x), _asarray(dtype, tx)


def inexact_asarray(x):
    dtype = jnp.result_type(x)
    if not jnp.issubdtype(jnp.result_type(x), jnp.inexact):
        dtype = default_floating_dtype()
    return _asarray(dtype, x)
