//
// NetworkEnvironmentService.cpp
//
// Library: IoT/NetworkEnvironment
// Package: NetworkEnvironment
// Module:  NetworkEnvironmentService
//
// Copyright (c) 2016, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "IoT/NetworkEnvironment/NetworkEnvironmentService.h"


namespace IoT {
namespace NetworkEnvironment {


NetworkEnvironmentService::NetworkEnvironmentService()
{
}


NetworkEnvironmentService::~NetworkEnvironmentService()
{
}


const std::type_info& NetworkEnvironmentService::type() const
{
	return typeid(NetworkEnvironmentService);
}


bool NetworkEnvironmentService::isA(const std::type_info& other) const
{
	return std::string(other.name()) == typeid(NetworkEnvironmentService).name() ||
		Poco::OSP::Service::isA(other);
}


} } // namespace IoT::NetworkEnvironment
