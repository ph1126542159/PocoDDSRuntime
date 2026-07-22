#include "PocoDDS/Control/ContractCodec.h"

#include <limits>
#include <stdexcept>
#include <type_traits>
#include <utility>

namespace PocoDDS::Control
{
namespace
{
constexpr std::uint32_t Magic = 0x50445243U;
enum class Kind : std::uint8_t
{
    Component = 1,
    Configuration = 2,
    Lifecycle = 3,
    Result = 4
};

template <typename T, bool IsEnum = std::is_enum_v<T>> struct RawNumber
{
    using type = T;
};

template <typename T> struct RawNumber<T, true>
{
    using type = std::underlying_type_t<T>;
};

class Writer
{
  public:
    template <typename T> void number(T value)
    {
        static_assert(std::is_integral_v<T> || std::is_enum_v<T>);
        using Raw = typename RawNumber<T>::type;
        using Unsigned = std::make_unsigned_t<Raw>;
        auto encoded = static_cast<Unsigned>(value);
        for (std::size_t index = 0; index < sizeof(Unsigned); ++index)
            _data.push_back(std::byte((encoded >> (index * 8U)) & 0xffU));
    }

    void string(const std::string& value)
    {
        if (value.size() > std::numeric_limits<std::uint32_t>::max())
            throw std::length_error("contract string is too large");
        number(static_cast<std::uint32_t>(value.size()));
        for (const auto character : value)
            _data.push_back(std::byte(static_cast<unsigned char>(character)));
    }

    void header(Kind kind, std::uint16_t version)
    {
        number(Magic);
        number(kind);
        number(version);
    }

    std::vector<std::byte> finish() { return std::move(_data); }

  private:
    std::vector<std::byte> _data;
};

class Reader
{
  public:
    explicit Reader(const std::vector<std::byte>& data) : _data(data) {}

    template <typename T> T number()
    {
        static_assert(std::is_integral_v<T> || std::is_enum_v<T>);
        using Raw = typename RawNumber<T>::type;
        using Unsigned = std::make_unsigned_t<Raw>;
        require(sizeof(Unsigned));
        Unsigned result{0};
        for (std::size_t index = 0; index < sizeof(Unsigned); ++index)
            result |= static_cast<Unsigned>(std::to_integer<unsigned int>(_data[_offset++]))
                      << (index * 8U);
        return static_cast<T>(result);
    }

    std::string string()
    {
        const auto size = number<std::uint32_t>();
        require(size);
        std::string value;
        value.reserve(size);
        for (std::uint32_t index = 0; index < size; ++index)
            value.push_back(static_cast<char>(std::to_integer<unsigned char>(_data[_offset++])));
        return value;
    }

    std::uint16_t header(Kind expected)
    {
        if (number<std::uint32_t>() != Magic)
            throw std::invalid_argument("invalid contract magic");
        if (number<Kind>() != expected)
            throw std::invalid_argument("unexpected contract kind");
        const auto version = number<std::uint16_t>();
        if (version != ContractVersion)
            throw std::invalid_argument("unsupported contract version");
        return version;
    }

    void complete() const
    {
        if (_offset != _data.size())
            throw std::invalid_argument("trailing contract data");
    }

  private:
    void require(std::size_t size) const
    {
        if (size > _data.size() - _offset)
            throw std::invalid_argument("truncated contract data");
    }

    const std::vector<std::byte>& _data;
    std::size_t _offset{0};
};

void encodeMap(Writer& writer, const std::map<std::string, std::string>& values)
{
    writer.number(static_cast<std::uint32_t>(values.size()));
    for (const auto& [key, value] : values)
    {
        writer.string(key);
        writer.string(value);
    }
}

std::map<std::string, std::string> decodeMap(Reader& reader)
{
    const auto size = reader.number<std::uint32_t>();
    if (size > 10000U)
        throw std::invalid_argument("contract map entry limit exceeded");
    std::map<std::string, std::string> values;
    for (std::uint32_t index = 0; index < size; ++index)
    {
        auto key = reader.string();
        auto value = reader.string();
        if (!values.emplace(std::move(key), std::move(value)).second)
            throw std::invalid_argument("duplicate contract map key");
    }
    return values;
}
} // namespace

std::vector<std::byte> encode(const ComponentManifest& value)
{
    Writer writer;
    writer.header(Kind::Component, value.version);
    writer.string(value.nodeId);
    writer.string(value.component.id);
    writer.string(value.component.name);
    writer.string(value.component.host);
    writer.number<std::int32_t>(value.component.processId);
    writer.number(value.component.kind);
    writer.number(value.component.state);
    encodeMap(writer, value.component.metadata);
    writer.number(value.heartbeatUnixMilliseconds);
    writer.number(value.leaseMilliseconds);
    return writer.finish();
}

std::vector<std::byte> encode(const ConfigurationTransaction& value)
{
    Writer writer;
    writer.header(Kind::Configuration, value.version);
    writer.string(value.correlationId);
    writer.string(value.targetComponentId);
    writer.number(value.expectedRevision);
    encodeMap(writer, value.changes);
    return writer.finish();
}

std::vector<std::byte> encode(const LifecycleCommand& value)
{
    Writer writer;
    writer.header(Kind::Lifecycle, value.version);
    writer.string(value.correlationId);
    writer.string(value.targetComponentId);
    writer.number(value.action);
    writer.number(value.gracefulTimeoutMilliseconds);
    return writer.finish();
}

std::vector<std::byte> encode(const CommandResult& value)
{
    Writer writer;
    writer.header(Kind::Result, value.version);
    writer.string(value.correlationId);
    writer.string(value.targetComponentId);
    writer.number<std::uint8_t>(value.success ? 1U : 0U);
    writer.string(value.error);
    writer.number(value.configurationRevision);
    return writer.finish();
}

ComponentManifest decodeComponentManifest(const std::vector<std::byte>& data)
{
    Reader reader(data);
    ComponentManifest value;
    value.version = reader.header(Kind::Component);
    value.nodeId = reader.string();
    value.component.id = reader.string();
    value.component.name = reader.string();
    value.component.host = reader.string();
    value.component.processId = reader.number<std::int32_t>();
    value.component.kind = reader.number<Core::ComponentKind>();
    value.component.state = reader.number<Core::ComponentState>();
    value.component.metadata = decodeMap(reader);
    value.heartbeatUnixMilliseconds = reader.number<std::int64_t>();
    value.leaseMilliseconds = reader.number<std::uint32_t>();
    reader.complete();
    if (value.nodeId.empty() || value.component.id.empty())
        throw std::invalid_argument("component contract requires node and component id");
    return value;
}

ConfigurationTransaction decodeConfigurationTransaction(const std::vector<std::byte>& data)
{
    Reader reader(data);
    ConfigurationTransaction value;
    value.version = reader.header(Kind::Configuration);
    value.correlationId = reader.string();
    value.targetComponentId = reader.string();
    value.expectedRevision = reader.number<std::uint64_t>();
    value.changes = decodeMap(reader);
    reader.complete();
    return value;
}

LifecycleCommand decodeLifecycleCommand(const std::vector<std::byte>& data)
{
    Reader reader(data);
    LifecycleCommand value;
    value.version = reader.header(Kind::Lifecycle);
    value.correlationId = reader.string();
    value.targetComponentId = reader.string();
    value.action = reader.number<LifecycleAction>();
    value.gracefulTimeoutMilliseconds = reader.number<std::uint32_t>();
    reader.complete();
    return value;
}

CommandResult decodeCommandResult(const std::vector<std::byte>& data)
{
    Reader reader(data);
    CommandResult value;
    value.version = reader.header(Kind::Result);
    value.correlationId = reader.string();
    value.targetComponentId = reader.string();
    const auto success = reader.number<std::uint8_t>();
    if (success > 1U)
        throw std::invalid_argument("invalid command result boolean");
    value.success = success == 1U;
    value.error = reader.string();
    value.configurationRevision = reader.number<std::uint64_t>();
    reader.complete();
    return value;
}
} // namespace PocoDDS::Control
