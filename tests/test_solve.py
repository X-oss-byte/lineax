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

import jax
import jax.numpy as jnp
import jax.random as jr
import pytest

import lineax as lx

from .helpers import shaped_allclose


def test_gmres_large_dense(getkey):
    tol = 1e-10 if jax.config.jax_enable_x64 else 1e-4
    solver = lx.GMRES(atol=tol, rtol=tol, restart=100)

    matrix = jr.normal(getkey(), (100, 100))
    operator = lx.MatrixLinearOperator(matrix)
    true_x = jr.normal(getkey(), (100,))
    b = matrix @ true_x

    lx_soln = lx.linear_solve(operator, b, solver).value

    assert shaped_allclose(lx_soln, true_x, atol=tol, rtol=tol)


def test_nontrivial_pytree_operator():
    x = [[1, 5.0], [jnp.array(-2), jnp.array(-2.0)]]
    y = [3, 4]
    struct = jax.eval_shape(lambda: y)
    operator = lx.PyTreeLinearOperator(x, struct)
    out = lx.linear_solve(operator, y).value
    true_out = [jnp.array(-3.25), jnp.array(1.25)]
    assert shaped_allclose(out, true_out)


@pytest.mark.parametrize("solver", (lx.LU(), lx.QR(), lx.SVD()))
def test_mixed_dtypes(solver):
    f32 = lambda x: jnp.array(x, dtype=jnp.float32)
    f64 = lambda x: jnp.array(x, dtype=jnp.float64)
    x = [[f32(1), f64(5)], [f32(-2), f64(-2)]]
    y = [f64(3), f64(4)]
    struct = jax.eval_shape(lambda: y)
    operator = lx.PyTreeLinearOperator(x, struct)
    out = lx.linear_solve(operator, y, solver=solver).value
    true_out = [f32(-3.25), f64(1.25)]
    assert shaped_allclose(out, true_out)


def test_mixed_dtypes_triangular():
    f32 = lambda x: jnp.array(x, dtype=jnp.float32)
    f64 = lambda x: jnp.array(x, dtype=jnp.float64)
    x = [[f32(1), f64(0)], [f32(-2), f64(-2)]]
    y = [f64(3), f64(4)]
    struct = jax.eval_shape(lambda: y)
    operator = lx.PyTreeLinearOperator(x, struct, lx.lower_triangular_tag)
    out = lx.linear_solve(operator, y, solver=lx.Triangular()).value
    true_out = [f32(3), f64(-5)]
    assert shaped_allclose(out, true_out)


def test_ad_closure_function_linear_operator(getkey):
    def f(x, z):
        def fn(y):
            return x * y

        op = lx.FunctionLinearOperator(fn, jax.eval_shape(lambda: z))
        sol = lx.linear_solve(op, z).value
        return jnp.sum(sol), sol

    x = jr.normal(getkey(), (3,))
    x = jnp.where(jnp.abs(x) < 1e-6, 0.7, x)
    z = jr.normal(getkey(), (3,))
    grad, sol = jax.grad(f, has_aux=True)(x, z)
    assert shaped_allclose(grad, -z / (x**2))
    assert shaped_allclose(sol, z / x)
