import pytest

from carma.indexers.libclang.ids import escape, file_segment, norm_type


@pytest.mark.parametrize(
    "written,normalized",
    [
        ("const std::string &", "const std::string&"),
        ("const char *const", "const char*const"),
        ("std::function<void ()>", "std::function<void()>"),
        ("std::map<int,int>", "std::map<int, int>"),
        ("void (*)(int)", "void(*)(int)"),
        ("int (&)[3]", "int(&)[3]"),
        ("unsigned  long   long", "unsigned long long"),
        ("std::size_t", "std::size_t"),
        ("void (*)() __attribute__((cdecl))", "void(*)()"),
        ("void (__cdecl *)(int)", "void(*)(int)"),
    ],
)
def test_norm_type(written, normalized):
    assert norm_type(written) == normalized


def test_escape():
    assert escape("DrawScene") == "DrawScene"
    assert escape("operator=") == "`operator=`"
    assert escape("~Mesh") == "`~Mesh`"
    assert escape("a`b") == "`a``b`"


def test_file_segment():
    assert file_segment("src/io/IoQueue.cpp") == "`src/io/IoQueue.cpp`/"
