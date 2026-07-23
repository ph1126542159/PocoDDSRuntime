#pragma once

#include "PocoDDS/DDS/Envelope.h"

#include <fastdds/dds/topic/TopicDataType.hpp>

namespace PocoDDS::FastDDS
{
class EnvelopeTopicDataType final : public eprosima::fastdds::dds::TopicDataType
{
public:
    EnvelopeTopicDataType();

    bool serialize(const void* const data,
                   eprosima::fastdds::rtps::SerializedPayload_t& payload,
                   eprosima::fastdds::dds::DataRepresentationId_t representation) override;
    bool deserialize(eprosima::fastdds::rtps::SerializedPayload_t& payload, void* data) override;
    std::uint32_t calculate_serialized_size(
        const void* const data,
        eprosima::fastdds::dds::DataRepresentationId_t representation) override;
    bool compute_key(eprosima::fastdds::rtps::SerializedPayload_t& payload,
                     eprosima::fastdds::rtps::InstanceHandle_t& handle,
                     bool forceMd5 = false) override;
    bool compute_key(const void* const data,
                     eprosima::fastdds::rtps::InstanceHandle_t& handle,
                     bool forceMd5 = false) override;
    void* create_data() override;
    void delete_data(void* data) override;
    void register_type_object_representation() override;
};
} // namespace PocoDDS::FastDDS
