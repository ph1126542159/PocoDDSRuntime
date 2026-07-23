//
// DeviceStatusService.cpp
//
// Library: IoT/DeviceStatus
// Package: DeviceStatusService
// Module:  DeviceStatusService
//
// Copyright (c) 2016, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "IoT/DeviceStatus/DeviceStatusService.h"


namespace IoT {
namespace DeviceStatus {


DeviceStatusService::DeviceStatusService()
{
}

	
DeviceStatusService::~DeviceStatusService()
{
}


const std::type_info& DeviceStatusService::type() const
{
	return typeid(DeviceStatusService);
}


bool DeviceStatusService::isA(const std::type_info& other) const
{
	return std::string(other.name()) == typeid(DeviceStatusService).name() ||
		Poco::OSP::Service::isA(other);
}


} } // namespace IoT::DeviceStatus
