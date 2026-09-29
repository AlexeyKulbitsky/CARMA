#pragma once

#include <array>
#include <cstddef>

namespace golden::io {

template <typename T, std::size_t N = 8>
class RingBuffer {
public:
    void Push(const T& value) { m_data[m_head++ % N] = value; }
    std::size_t Size() const { return m_head < N ? m_head : N; }

private:
    std::array<T, N> m_data{};
    std::size_t m_head = 0;
};

// Explicit specialization: its ID carries the template arguments.
template <>
class RingBuffer<bool, 8> {
public:
    void Push(bool value) { m_bits = static_cast<unsigned char>((m_bits << 1) | (value ? 1 : 0)); }
    std::size_t Size() const { return 8; }

private:
    unsigned char m_bits = 0;
};

}  // namespace golden::io
