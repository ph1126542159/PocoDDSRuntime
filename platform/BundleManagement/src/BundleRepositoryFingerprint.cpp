#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"

#include "Poco/DigestEngine.h"
#include "Poco/Exception.h"
#include "Poco/SHA2Engine.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string_view>
#include <vector>

namespace PocoDDS::BundleManagement
{
namespace
{
namespace fs = std::filesystem;

struct Entry
{
    fs::path absolute;
    std::string relative;
    char type;
};

void update(Poco::DigestEngine& engine, std::string_view value)
{
    const std::uint64_t size = static_cast<std::uint64_t>(value.size());
    std::array<unsigned char, 8> encoded{};
    for (std::size_t index = 0; index < encoded.size(); ++index)
        encoded[encoded.size() - index - 1] =
            static_cast<unsigned char>((size >> (index * 8)) & 0xffU);
    engine.update(encoded.data(), encoded.size());
    if (!value.empty())
        engine.update(value.data(), value.size());
}

void updateSize(Poco::DigestEngine& engine, std::uint64_t size)
{
    std::array<unsigned char, 8> encoded{};
    for (std::size_t index = 0; index < encoded.size(); ++index)
        encoded[encoded.size() - index - 1] =
            static_cast<unsigned char>((size >> (index * 8)) & 0xffU);
    engine.update(encoded.data(), encoded.size());
}

std::string calculateOnce(const std::string& repositoryDirectory)
{
    std::error_code error;
    const fs::path root = fs::absolute(fs::u8path(repositoryDirectory), error).lexically_normal();
    if (error || !fs::exists(root) || !fs::is_directory(root))
        throw Poco::FileNotFoundException("Bundle repository directory", repositoryDirectory);

    std::vector<Entry> entries;
    for (fs::recursive_directory_iterator iterator(root, error), end;
         !error && iterator != end; iterator.increment(error))
    {
        const fs::file_status status = iterator->symlink_status(error);
        if (error) break;
        char type = 0;
        if (fs::is_regular_file(status)) type = 'F';
        else if (fs::is_directory(status)) type = 'D';
        else if (fs::is_symlink(status)) type = 'L';
        else
            throw Poco::InvalidArgumentException(
                "Unsupported entry in Bundle repository", iterator->path().u8string());
        entries.push_back({iterator->path(),
                           iterator->path().lexically_relative(root).generic_u8string(), type});
    }
    if (error)
        throw Poco::FileException("Cannot enumerate Bundle repository: " + error.message(),
                                  repositoryDirectory);
    if (entries.empty())
        throw Poco::InvalidArgumentException("Bundle repository is empty", repositoryDirectory);

    std::sort(entries.begin(), entries.end(), [](const Entry& left, const Entry& right) {
        return left.relative < right.relative;
    });

    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    update(engine, "PDR-BUNDLE-REPOSITORY/1");
    std::array<char, 64 * 1024> buffer{};
    for (const auto& entry : entries)
    {
        engine.update(&entry.type, sizeof(entry.type));
        update(engine, entry.relative);
        if (entry.type == 'L')
        {
            update(engine, fs::read_symlink(entry.absolute, error).generic_u8string());
            if (error)
                throw Poco::FileException("Cannot read Bundle repository symlink: " + error.message(),
                                          entry.absolute.u8string());
        }
        else if (entry.type == 'F')
        {
            const auto expectedSize = fs::file_size(entry.absolute, error);
            if (error)
                throw Poco::FileException("Cannot stat Bundle repository file: " + error.message(),
                                          entry.absolute.u8string());
            updateSize(engine, static_cast<std::uint64_t>(expectedSize));
            std::ifstream stream(entry.absolute, std::ios::binary);
            if (!stream.good())
                throw Poco::OpenFileException(entry.absolute.u8string());
            std::uint64_t bytesRead = 0;
            while (stream.good())
            {
                stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
                const auto count = stream.gcount();
                if (count > 0)
                {
                    engine.update(buffer.data(), static_cast<std::size_t>(count));
                    bytesRead += static_cast<std::uint64_t>(count);
                }
            }
            if (!stream.eof())
                throw Poco::ReadFileException(entry.absolute.u8string());
            const auto finalSize = fs::file_size(entry.absolute, error);
            if (error || bytesRead != expectedSize || finalSize != expectedSize)
                throw Poco::FileException("Bundle repository changed while hashing",
                                          entry.absolute.u8string());
        }
    }
    return Poco::DigestEngine::digestToHex(engine.digest());
}
} // namespace

std::string BundleRepositoryFingerprint::calculateDirectory(
    const std::string& repositoryDirectory)
{
    const std::string first = calculateOnce(repositoryDirectory);
    const std::string second = calculateOnce(repositoryDirectory);
    if (first != second)
        throw Poco::FileException("Bundle repository changed while fingerprinting",
                                  repositoryDirectory);
    return first;
}
} // namespace PocoDDS::BundleManagement
