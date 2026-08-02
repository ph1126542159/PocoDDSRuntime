#pragma once

#include "PocoDDS/Protocols/Serial/SerialChannel.h"

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::Serial
{
class LoopbackSerialChannel final : public ISerialChannel
{
public:
    explicit LoopbackSerialChannel(std::string channelName = "loopback");

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;
    std::size_t write(const std::uint8_t* data, std::size_t size) override;
    std::vector<std::uint8_t> read(std::size_t size, Poco::Timespan timeout) override;

private:
    std::string _name;
    mutable std::mutex _mutex;
    std::condition_variable _ready;
    std::deque<std::uint8_t> _bytes;
    bool _open{false};
};
}
