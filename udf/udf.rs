// Exact fractions for the calculation rules (docs/compiler.md, "Rekenen"): the Feldera side of the
// functions that DuckDB has as SQL macros (compiler/rede_compiler/calc_sql.py). Pure functions over
// (numerator, denominator > 0) pairs of i64, computed in i128. A result denominator of 0 marks
// overflow or division by zero; the generated SQL turns that into the state `invalid`.

use std::error::Error;

type Out = Result<i64, Box<dyn Error>>;

const BOUND: i128 = i64::MAX as i128;

fn gcd(a: i128, b: i128) -> i128 {
    let (mut a, mut b) = (a.abs(), b.abs());
    while b != 0 {
        let t = a % b;
        a = b;
        b = t;
    }
    a
}

/// n / d in lowest terms with d > 0, or (0, 0) when it does not fit 64 bits.
fn fit(n: i128, d: i128) -> (i64, i64) {
    if d <= 0 {
        return (0, 0);
    }
    let g = gcd(n, d).max(1);
    let (n, d) = (n / g, d / g);
    if n.abs() > BOUND || d > BOUND {
        (0, 0)
    } else {
        (n as i64, d as i64)
    }
}

fn add(an: i64, ad: i64, bn: i64, bd: i64, sign: i128) -> (i64, i64) {
    if ad <= 0 || bd <= 0 {
        return (0, 0);
    }
    let (an, ad, bn, bd) = (an as i128, ad as i128, bn as i128, bd as i128);
    fit(an * bd + sign * bn * ad, ad * bd)
}

fn mul(an: i64, ad: i64, bn: i64, bd: i64) -> (i64, i64) {
    if ad <= 0 || bd <= 0 {
        return (0, 0);
    }
    fit(an as i128 * bn as i128, ad as i128 * bd as i128)
}

fn div(an: i64, ad: i64, bn: i64, bd: i64) -> (i64, i64) {
    if ad <= 0 || bd <= 0 || bn == 0 {
        return (0, 0);
    }
    let (n, d) = (an as i128 * bd as i128, ad as i128 * bn as i128);
    if d < 0 { fit(-n, -d) } else { fit(n, d) }
}

pub fn rede_add_n(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(add(an, ad, bn, bd, 1).0) }
pub fn rede_add_d(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(add(an, ad, bn, bd, 1).1) }
pub fn rede_sub_n(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(add(an, ad, bn, bd, -1).0) }
pub fn rede_sub_d(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(add(an, ad, bn, bd, -1).1) }
pub fn rede_mul_n(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(mul(an, ad, bn, bd).0) }
pub fn rede_mul_d(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(mul(an, ad, bn, bd).1) }
pub fn rede_div_n(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(div(an, ad, bn, bd).0) }
pub fn rede_div_d(an: i64, ad: i64, bn: i64, bd: i64) -> Out { Ok(div(an, ad, bn, bd).1) }

pub fn rede_cmp(an: i64, ad: i64, bn: i64, bd: i64) -> Out {
    let (l, r) = (an as i128 * bd as i128, bn as i128 * ad as i128);
    Ok(if l < r { -1 } else if l > r { 1 } else { 0 })
}

/// Largest integer not above n / d.
pub fn rede_floor(n: i64, d: i64) -> Out {
    if d <= 0 { return Ok(0); }
    Ok((n as i128).div_euclid(d as i128) as i64)
}

/// Smallest integer not below n / d.
pub fn rede_ceil(n: i64, d: i64) -> Out {
    if d <= 0 { return Ok(0); }
    Ok(-((-(n as i128)).div_euclid(d as i128)) as i64)
}

/// Half away from zero: sign(x) * floor(|x| + 1/2).
pub fn rede_round(n: i64, d: i64) -> Out {
    if d <= 0 { return Ok(0); }
    let (m, d) = ((n as i128).abs(), d as i128);
    let r = (2 * m + d) / (2 * d);
    Ok((if n < 0 { -r } else { r }) as i64)
}

/// Bit log2(p) of e: (e / p) mod 2, for e >= 0 and p > 0.
pub fn rede_bit(e: i64, p: i64) -> Out {
    if e < 0 || p <= 0 { return Ok(0); }
    Ok((e / p) % 2)
}
