//
// MobileConnectionService.cpp
//
// Library: IoT/MobileConnection
// Package: MobileConnection
// Module:  MobileConnectionService
//
// Copyright (c) 2017, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "IoT/MobileConnection/MobileConnectionService.h"


namespace IoT {
namespace MobileConnection {


MobileConnectionService::MobileConnectionService()
{
}


MobileConnectionService::~MobileConnectionService()
{
}


const std::type_info& MobileConnectionService::type() const
{
	return typeid(MobileConnectionService);
}


bool MobileConnectionService::isA(const std::type_info& other) const
{
	return std::string(other.name()) == typeid(MobileConnectionService).name() ||
		Poco::OSP::Service::isA(other);
}


} } // namespace IoT::MobileConnection
